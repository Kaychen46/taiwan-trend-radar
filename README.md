# 台灣爆點雷達

這是靜態網站。GitHub Actions 每天在台灣時間 15:00 執行資料管線，產出 `data/latest_trends.json`，並將當次的 `index.html` 與 JSON 一起發布到 GitHub Pages。排程以 UTC 07:00 設定，實際執行可能延遲；GitHub 說明見 [排程事件文件](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。

## 資料與標示

- 訊號來自 Google Trends 台灣 RSS、[數位時代的 RSS](https://rss.bnextmedia.com.tw/feed/bnext)、Google News 搜尋摘要、PTT 看板 Atom 摘要，以及有設定金鑰時的 YouTube 熱門影片。網站上的 AI 摘要與商業切角是模型分析，應點開每則報告的來源自行核對。數位時代原使用的 `/rss` 網址已回傳 404；新 RSS 入口若未提供文章，會標示為近期無資料，不會補造內容。
- PTT 優先使用 [看板 Atom 摘要](https://www.ptt.cc/bbs/PttNewhand/M.1588097847.A.41D.html)取得近期文章。Stock 的官方 Atom 與看板頁面曾在 [GitHub runner 檢查](https://github.com/Kaychen46/taiwan-trend-radar/actions/runs/45035395520)回傳 403；只有直取失敗時，才從 [Google 新聞的 PTT Stock 搜尋摘要](https://news.google.com/rss/search?q=site%3Aptt.cc%2Fbbs%2FStock%20when%3A1d&hl=zh-TW&gl=TW&ceid=TW%3Azh-Hant)選取近期且明確標為 Stock 看板的標題。這是索引補充，連結會先到 Google 新聞，不能代表完整看板或原始標題全文。Atom 與索引都不提供推文數。
- JSON 的 `ptt_status` 區分官方直取 `available`、索引補充 `indexed`、近期無文章 `empty`、未取得 `unavailable`。`source_status` 記錄各來源在過濾後的採集數量，以及 `available`、`indexed`、`empty`、`unavailable` 或選用來源未設定的 `not_configured` 狀態；網站的「來源採集明細」會顯示這些狀態。採集數量可能高於實際送入模型的 65 則上限；上限見 [管線設定](https://github.com/Kaychen46/taiwan-trend-radar/blob/main/pipeline_mvp.py)。
- 只採用有可解析發布時間且在 36 小時內的 RSS／PTT 文章。模型輸出的來源網址必須與採集訊號的網址相同；沒有可核對來源的報告不發布。報告也會列出當時採集到的來源標題，方便核對 AI 摘要。
- 若 JSON 不存在或沒有報告，網站顯示固定的示範內容與不可隱藏的示範標籤。示範內容並非真實趨勢，也不提供原始來源連結。資料超過 26 小時未更新時，網站會提示時效。

## 啟用 GitHub Pages

1. 在儲存庫 Settings → Pages，將 **Build and deployment → Source** 設為 **GitHub Actions**。此設定方法見 [GitHub Pages 發布來源文件](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)。
2. 在儲存庫 Actions secrets 設定 `LLM_API_KEY`（Gemini API key）。`YOUTUBE_API_KEY` 與 `DISCORD_WEBHOOK_URL` 是選用項目。不要把金鑰寫入原始碼或 issue。Gemini 模型與相容 API 依 [Google Gemini 文件](https://ai.google.dev/gemini-api/docs) 設定。
3. 更新 `main`、排程到時或手動啟動時，**Taiwan Trend Radar Pipeline** 都會執行。確認 `run-pipeline` 與 `deploy-pages` 都成功，再開啟 Pages 網址核對資料與來源。Pages 自訂工作流程所需的 artifact、權限與環境設定見 [GitHub 官方範例](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)。

排程或手動執行失敗時，既有 Pages 部署不會自動消失；網站會保留上次成功發布的 JSON，並在超過 26 小時時顯示過期提示。
