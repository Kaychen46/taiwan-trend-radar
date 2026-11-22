# 台灣爆點雷達

這是靜態網站。GitHub Actions 每天在台灣時間 08:00、12:00、16:00、20:00 執行資料管線，產出 `data/latest_trends.json`，並將當次的 `index.html` 與 JSON 一起發布到 GitHub Pages。排程以 UTC 設定，實際執行可能延遲；GitHub 說明見 [排程事件文件](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。

## 資料與標示

- 訊號來自 Google Trends 台灣 RSS、數位時代 RSS、Google News 搜尋摘要、PTT 看板 Atom 摘要，以及有設定金鑰時的 YouTube 熱門影片。網站上的 AI 摘要與商業切角是模型分析，應點開每則報告的原始來源自行核對。
- PTT 使用 [看板 Atom 摘要](https://www.ptt.cc/bbs/PttNewhand/M.1588097847.A.41D.html)取得近期文章。Atom 不提供推文數，所以網站不宣稱這些文章達到特定推文門檻。來源失敗時，JSON 的 `ptt_status` 與網站提示會顯示狀態。
- 只採用有可解析發布時間且在 36 小時內的 RSS／PTT 文章。模型輸出的來源網址必須與採集訊號的網址相同；沒有可核對來源的報告不發布。
- 若 JSON 不存在或沒有報告，網站顯示固定的示範內容與不可隱藏的示範標籤。示範內容並非真實趨勢，也不提供原始來源連結。資料超過 12 小時未更新時，網站會提示時效。

## 啟用 GitHub Pages

1. 在儲存庫 Settings → Pages，將 **Build and deployment → Source** 設為 **GitHub Actions**。此設定方法見 [GitHub Pages 發布來源文件](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)。
2. 在儲存庫 Actions secrets 設定 `LLM_API_KEY`（Gemini API key）。`YOUTUBE_API_KEY` 與 `DISCORD_WEBHOOK_URL` 是選用項目。不要把金鑰寫入原始碼或 issue。Gemini 模型與相容 API 依 [Google Gemini 文件](https://ai.google.dev/gemini-api/docs) 設定。
3. 合併含本工作流程的 PR 後，手動執行 **Taiwan Trend Radar Pipeline**，確認 `run-pipeline` 與 `deploy-pages` 都成功，再開啟 Pages 網址核對資料與來源。Pages 自訂工作流程所需的 artifact、權限與環境設定見 [GitHub 官方範例](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)。

排程或手動執行失敗時，既有 Pages 部署不會自動消失；網站會保留上次成功發布的 JSON，並在超過 12 小時時顯示過期提示。
