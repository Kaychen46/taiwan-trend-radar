import os
import json
import re
import urllib.parse
from datetime import datetime, timezone, timedelta
from calendar import timegm
import feedparser
import requests
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# ==========================================
# 1. 系統設定與硬性熔斷上限 (Hard Cap)
# ==========================================
MAX_ITEMS_PER_SOURCE = 15       # 每個來源最多抓 15 則
MAX_SIGNALS_TO_AI = 65          # 每次送給 AI 聚類的訊號上限
MAX_FINAL_REPORTS = 12          # 對齊前端：4 大分類各 2-3 則，共 12 則
MAX_PTT_ITEMS_PER_BOARD = 6
MIN_COMMERCIAL_VALUE = 3        # 商業價值守門員門檻（1-5分）
MAX_SIGNAL_AGE = timedelta(hours=36)

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
def is_recent(entry: dict) -> bool:
    published = entry.get("published_parsed") or entry.get("updated_parsed")
    if not published:
        return False
    published_at = datetime.fromtimestamp(timegm(published), timezone.utc)
    age = datetime.now(timezone.utc) - published_at
    return timedelta(0) <= age <= MAX_SIGNAL_AGE


def fetch_rss_signals() -> tuple[list[dict], dict]:
    signals = []
    status = {}
    for src in RSS_SOURCES:
        try:
            feed = feedparser.parse(src["url"])
            if feed.bozo and not feed.entries:
                raise ValueError(f"RSS 摘要格式錯誤: {feed.bozo_exception}")
            source_signals = []
            for entry in feed.entries[:MAX_ITEMS_PER_SOURCE]:
                if not is_recent(entry):
                    continue
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                if is_noise(title) or not link.startswith("https://"):
                    continue
                source_signals.append({
                    "source": src["name"],
                    "source_type": src["type"],
                    "title": title,
                    "url": link,
                    "metric": "RSS熱門"
                })
            signals.extend(source_signals)
            count = len(source_signals)
            status[src["name"]] = {"state": "available" if count else "empty", "count": count}
        except Exception as e:
            print(f"[Warning] RSS {src['name']} 抓取失敗: {e}")
            status[src["name"]] = {"state": "unavailable", "count": 0}
    return signals, status


def fetch_ptt_stock_indexed() -> list[dict]:
    """Stock 官方入口不可用時，採用明確標示的 Google 新聞索引標題。"""
    res = requests.get(
        "https://news.google.com/rss/search",
        params={"q": "site:ptt.cc/bbs/Stock when:1d", "hl": "zh-TW", "gl": "TW", "ceid": "TW:zh-Hant"},
        timeout=10,
    )
    res.raise_for_status()
    feed = feedparser.parse(res.content)
    if feed.bozo and not feed.entries:
        raise ValueError("Stock 索引摘要格式錯誤")
    signals = []
    suffix = " - 看板 Stock - ptt.cc"
    for entry in feed.entries:
        title = entry.get("title", "").strip()
        link = entry.get("link", "").strip()
        if not title.endswith(suffix) or not is_recent(entry):
            continue
        title = title[:-len(suffix)].strip()
        if is_noise(title) or not link.startswith("https://news.google.com/rss/articles/"):
            continue
        signals.append({
            "source": "PTT_Stock_索引",
            "source_type": "forum_proxy",
            "title": title,
            "url": link,
            "metric": "Google 新聞索引的 PTT Stock 標題（非官方 Atom、無推文數）",
        })
        if len(signals) >= MAX_PTT_ITEMS_PER_BOARD:
            break
    return signals


def fetch_ptt_recent(boards: list[str] = None) -> tuple[list[dict], dict]:
    if boards is None:
        boards = ["Gossiping", "Stock", "Lifeismoney"]
    signals = []
    status = {}

    for board in boards:
        try:
            url = f"https://www.ptt.cc/atom/{board}.xml"
            res = requests.get(url, timeout=10)
            res.raise_for_status()
            feed = feedparser.parse(res.content)
            if feed.bozo and not feed.entries:
                raise ValueError("Atom 摘要格式錯誤")
            count = 0
            for entry in feed.entries:
                if not is_recent(entry):
                    continue
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                if is_noise(title) or not link.startswith("https://www.ptt.cc/bbs/"):
                    continue
                signals.append({
                    "source": f"PTT_{board}",
                    "source_type": "forum",
                    "title": title,
                    "url": link,
                    "metric": "PTT 近期文章（未提供推文數）"
                })
                count += 1
                if count >= MAX_PTT_ITEMS_PER_BOARD:
                    break
            status[board] = "available" if count else "empty"
        except Exception as e:
            print(f"[Warning] PTT {board} 抓取失敗: {e}")
            if board == "Stock":
                try:
                    indexed = fetch_ptt_stock_indexed()
                    if indexed:
                        signals.extend(indexed)
                        status[board] = "indexed"
                        continue
                except Exception as indexed_error:
                    print(f"[Warning] PTT Stock 索引抓取失敗: {indexed_error}")
            status[board] = "unavailable"
    return signals, status


def fetch_youtube_trending_tw() -> tuple[list[dict], dict]:
    if not YOUTUBE_API_KEY:
        return [], {"YouTube_TW發燒": {"state": "not_configured", "count": 0}}

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
        return signals, {"YouTube_TW發燒": {"state": "unavailable", "count": len(signals)}}
    return signals, {"YouTube_TW發燒": {"state": "available" if signals else "empty", "count": len(signals)}}


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
我會提供台灣近 36 小時來自搜尋趨勢、商業媒體、PTT 近期文章、YouTube 發燒與社群破圈的公開標題清單。

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
      "reference_urls": ["從輸入訊號的 url 欄位原樣複製的連結1", "連結2"],
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
reference_urls 必須逐字複製輸入訊號的 url，不得編造、改寫或使用網站首頁。沒有來源連結的話題不要輸出。
事件脈絡只根據輸入標題撰寫；標題沒有提供的數字、價格、政策細節或醫療結論，不得當成已確認事實。
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
def verified_reports(reports: list[dict], signals: list[dict]) -> list[dict]:
    sources_by_url = {
        signal["url"]: {"source": signal["source"], "title": signal["title"]}
        for signal in signals
        if signal.get("url", "").startswith("https://")
    }
    verified = []
    for report in reports:
        if not isinstance(report, dict):
            continue
        urls = report.get("reference_urls") or []
        if not isinstance(urls, list):
            continue
        matched = list(dict.fromkeys(url for url in urls if isinstance(url, str) and url in sources_by_url))[:3]
        if not matched:
            print(f"[Warning] 略過沒有可核對來源的報告: {report.get('topic_name', '未命名')}")
            continue
        report["reference_urls"] = matched
        report["sources_involved"] = [sources_by_url[url]["source"] for url in matched]
        report["source_titles"] = [
            f"Google 新聞索引顯示：{sources_by_url[url]['title']}"
            if sources_by_url[url]["source"] == "PTT_Stock_索引"
            else sources_by_url[url]["title"]
            for url in matched
        ]
        verified.append(report)
    return verified[:MAX_FINAL_REPORTS]


def main():
    tz_tw = timezone(timedelta(hours=8))
    now_str = datetime.now(tz_tw).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now_str}] 啟動台灣爆點雷達 v2.1 (12題材版)...")

    try:
        rss_signals, rss_status = fetch_rss_signals()
        ptt_signals, ptt_status = fetch_ptt_recent()
        youtube_signals, youtube_status = fetch_youtube_trending_tw()

        source_status = dict(rss_status)
        for board, state in ptt_status.items():
            count = sum(signal["source"] in (f"PTT_{board}", f"PTT_{board}_索引") for signal in ptt_signals)
            source_status[f"PTT_{board}"] = {"state": state, "count": count}
        source_status.update(youtube_status)

        # Reserve space for PTT so it cannot be squeezed out by earlier RSS feeds.
        signals = (ptt_signals + rss_signals + youtube_signals)[:MAX_SIGNALS_TO_AI]
        if not signals:
            raise ValueError("未抓取到任何有效訊號，請檢查網路連線。")

        print(f"成功採集 {len(signals)} 則跨平台訊號，送入 Gemini 情報引擎...")
        result = analyze_trends_with_ai(signals)
        reports = verified_reports(result.get("trends", []), signals)
        if not reports:
            raise ValueError("AI 未產生任何附有可核對來源的報告。")

        output_payload = {
            "updated_at": now_str,
            "total_signals_scanned": len(signals),
            "ptt_status": ptt_status,
            "source_status": source_status,
            "trends": reports
        }

        os.makedirs("data", exist_ok=True)
        with open("data/latest_trends.json", "w", encoding="utf-8") as f:
            json.dump(output_payload, f, ensure_ascii=False, indent=2)

        top_lines = [f"🔥 **台灣爆點雷達更新 ({now_str})**"]
        for idx, t in enumerate(output_payload["trends"][:3], 1):
            badge = "🐎黑馬" if t.get("is_dark_horse") else "📈熱門"
            playbook = (t.get("creator_playbook") or ["請開啟網站查看完整報告"])[0]
            top_lines.append(f"{idx}. [{badge}] **{t.get('topic_name', '未命名話題')}** (熱度 {t.get('heat_score', '-')})\n   └ 切角：{playbook}")
        send_webhook("\n".join(top_lines))
        print(f"完成！共產出 {len(output_payload['trends'])} 則情報，已寫入 data/latest_trends.json")

    except Exception as e:
        error_msg = f"🚨 **台灣爆點雷達執行異常**：`{str(e)}`"
        print(error_msg)
        send_webhook(error_msg)
        raise


if __name__ == "__main__":
    main()
