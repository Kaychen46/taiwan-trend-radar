import os
import json
import re
import urllib.parse
from datetime import datetime, timezone, timedelta
import feedparser
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# ==========================================
# 1. 系統設定與硬性熔斷上限 (Hard Cap)
# ==========================================
MAX_ITEMS_PER_SOURCE = 15       # 每個來源最多抓 15 則
MAX_SIGNALS_TO_AI = 65          # 每次送給 AI 聚類的訊號上限
MAX_FINAL_REPORTS = 12          # 對齊前端：4 大分類各 2-3 則，共 12 則
MIN_COMMERCIAL_VALUE = 3        # 商業價值守門員門檻（1-5分）
PTT_MIN_PUSH = 30               # PTT 最低推文數門檻

NOISE_KEYWORDS = ["氣象", "降雨機率", "星座", "運勢", "威力彩", "大樂透", "今彩539", "地震速報", "公告"]

def build_google_news_rss(query: str) -> str:
    encoded = urllib.parse.quote(f"{query} when:1d")
    return f"https://news.google.com/rss/search?q={encoded}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"

RSS_SOURCES = [
    {"name": "GoogleTrends_TW", "type": "search", "url": "https://trends.google.com/trending/rss?geo=TW"},
    {"name": "數位時代", "type": "tech_biz", "url": "https://www.bnext.com.tw/rss"},
    {"name": "Threads_破圈代理", "type": "social_proxy", "url": build_google_news_rss("Threads 爆紅 OR 脆友 OR 網友熱議")},
    {"name": "Dcard_破圈代理", "type": "social_proxy", "url": build_google_news_rss("Dcard 熱議 OR 網友討論")},
    {"name": "財經投資代理", "type": "finance", "url": build_google_news_rss("ETF OR 台股 OR 財經 熱門")},
]

client = OpenAI(
    api_key=os.getenv("LLM_API_KEY"),
    base_url=os.getenv("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
)
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-3.5-flash-lite")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")


def is_noise(title: str) -> bool:
    return (not title) or any(kw in title for kw in NOISE_KEYWORDS)


# ==========================================
# 2. 多平台數據採集模組 (Metadata-Only)
# ==========================================
def fetch_rss_signals() -> list[dict]:
    signals = []
    for src in RSS_SOURCES:
        try:
            feed = feedparser.parse(src["url"])
            for entry in feed.entries[:MAX_ITEMS_PER_SOURCE]:
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                if is_noise(title):
                    continue
                signals.append({
                    "source": src["name"],
                    "source_type": src["type"],
                    "title": title,
                    "url": link,
                    "metric": "RSS熱門"
                })
        except Exception as e:
            print(f"[Warning] RSS {src['name']} 抓取失敗: {e}")
    return signals


def fetch_ptt_hot(boards: list[str] = None) -> list[dict]:
    if boards is None:
        boards = ["Gossiping", "Stock", "Lifeismoney"]
    signals = []
    headers = {"User-Agent": "Mozilla/5.0"}
    cookies = {"over18": "1"}

    for board in boards:
        try:
            url = f"https://www.ptt.cc/bbs/{board}/index.html"
            res = requests.get(url, headers=headers, cookies=cookies, timeout=10)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, "html.parser")
            count = 0

            for ent in soup.select(".r-ent"):
                nrec = ent.select_one(".nrec").text.strip()
                a_tag = ent.select_one(".title a")
                if not a_tag:
                    continue

                push_score = 100 if nrec == "爆" else (int(nrec) if nrec.isdigit() else 0)
                if push_score < PTT_MIN_PUSH:
                    continue

                title = a_tag.text.strip()
                if is_noise(title):
                    continue

                signals.append({
                    "source": f"PTT_{board}",
                    "source_type": "forum",
                    "title": title,
                    "url": "https://www.ptt.cc" + a_tag["href"],
                    "metric": f"推文:{nrec}"
                })
                count += 1
                if count >= 6:
                    break
        except Exception as e:
            print(f"[Warning] PTT {board} 抓取失敗: {e}")
    return signals


def fetch_youtube_trending_tw() -> list[dict]:
    if not YOUTUBE_API_KEY:
        return []

    signals = []
    try:
        url = "https://www.googleapis.com/youtube/v3/videos"
        params = {
            "part": "snippet,statistics",
            "chart": "mostPopular",
            "regionCode": "TW",
            "maxResults": 10,
            "key": YOUTUBE_API_KEY
        }
        res = requests.get(url, params=params, timeout=10)
        res.raise_for_status()
        for item in res.json().get("items", []):
            title = item["snippet"]["title"].strip()
            if is_noise(title):
                continue
            vid = item["id"]
            views = item.get("statistics", {}).get("viewCount", "N/A")
            signals.append({
                "source": "YouTube_TW發燒",
                "source_type": "video",
                "title": title,
                "url": f"https://www.youtube.com/watch?v={vid}",
                "metric": f"觀看:{views}"
            })
    except Exception as e:
        print(f"[Warning] YouTube 發燒抓取失敗: {e}")
    return signals


# ==========================================
# 3. AI 價值守門員 + 跨平台聚類 + 流量密碼拆解
# ==========================================
def clean_json_text(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    return raw


def analyze_trends_with_ai(signals: list[dict]) -> dict:
    system_prompt = f"""
你是一位頂尖的「台灣流量操盤手兼電商選品總監」。
我會提供台灣近 24 小時來自搜尋趨勢、商業媒體、PTT 熱門看板、YouTube 發燒與社群破圈的公開標題清單。

請執行以下三步驟，並嚴格輸出純 JSON 格式：
1. **跨平台聚類**：將討論同一事件或趨勢的標題合併為一個話題。
2. **商業價值守門員**：剔除純政治口水、無意義車禍/社會案件、明顯業配稿。只保留對「內容創作者／行銷人」或「電商／市場投資人」具備借勢價值的話題（commercial_value 須 >= {MIN_COMMERCIAL_VALUE}）。
3. **均衡產出與深度拆解**：選出最具看頭的 Top {MAX_FINAL_REPORTS} 話題，請盡量在「商業科技、消費生活、社群文化、財經投資」4 大分類中**各分配 2 到 3 則**，並依 heat_score 由高到低排序。

輸出 JSON 結構必須嚴格符合：
{{
  "trends": [
    {{
      "topic_name": "精煉的話題名稱",
      "category": "商業科技 | 消費生活 | 社群文化 | 財經投資",
      "is_dark_horse": true,
      "heat_score": 88,
      "dark_horse_score": 92,
      "commercial_value": 5,
      "sources_involved": ["GoogleTrends_TW", "PTT_Stock"],
      "reference_urls": ["原始連結1", "原始連結2"],
      "tldr": "30字內一針見血的事件脈絡",
      "viral_dna": {{
        "hook_type": "情緒鉤子類型（如：省錢焦慮、認知反差、獵奇共鳴）",
        "why_now": "為什麼是現在爆紅的底層邏輯"
      }},
      "creator_playbook": [
        "可直接套用的爆款標題公式或短影音開頭鉤子 1",
        "可直接套用的圖文/影片切角 2"
      ],
      "ecommerce_radar": "這波流量背後的消費意圖、潛在選品或品牌借勢機會"
    }}
  ]
}}
"""
    response = client.chat.completions.create(
        model=LLM_MODEL,
        response_format={"type": "json_object"},
        temperature=0.3,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(signals, ensure_ascii=False)}
        ]
    )
    cleaned = clean_json_text(response.choices[0].message.content)
    return json.loads(cleaned)


def send_webhook(message: str):
    if not WEBHOOK_URL:
        return
    try:
        requests.post(WEBHOOK_URL, json={"content": message}, timeout=10)
    except Exception as e:
        print(f"[Warning] Webhook 發送失敗: {e}")


# ==========================================
# 4. 主流程執行
# ==========================================
def main():
    tz_tw = timezone(timedelta(hours=8))
    now_str = datetime.now(tz_tw).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now_str}] 啟動台灣爆點雷達 v2.1 (12題材版)...")

    try:
        all_signals = []
        all_signals.extend(fetch_rss_signals())
        all_signals.extend(fetch_ptt_hot())
        all_signals.extend(fetch_youtube_trending_tw())

        signals = all_signals[:MAX_SIGNALS_TO_AI]
        if not signals:
            raise ValueError("未抓取到任何有效訊號，請檢查網路連線。")

        print(f"成功採集 {len(signals)} 則跨平台訊號，送入 Gemini 情報引擎...")
        result = analyze_trends_with_ai(signals)

        output_payload = {
            "updated_at": now_str,
            "total_signals_scanned": len(signals),
            "trends": result.get("trends", [])
        }

        os.makedirs("data", exist_ok=True)
        with open("data/latest_trends.json", "w", encoding="utf-8") as f:
            json.dump(output_payload, f, ensure_ascii=False, indent=2)

        top_lines = [f"🔥 **台灣爆點雷達更新 ({now_str})**"]
        for idx, t in enumerate(output_payload["trends"][:3], 1):
            badge = "🐎黑馬" if t.get("is_dark_horse") else "📈熱門"
            top_lines.append(f"{idx}. [{badge}] **{t['topic_name']}** (熱度 {t['heat_score']})\n   └ 切角：{t['creator_playbook'][0]}")
        send_webhook("\n".join(top_lines))
        print(f"完成！共產出 {len(output_payload['trends'])} 則情報，已寫入 data/latest_trends.json")

    except Exception as e:
        error_msg = f"🚨 **台灣爆點雷達執行異常**：`{str(e)}`"
        print(error_msg)
        send_webhook(error_msg)
        raise


if __name__ == "__main__":
    main()