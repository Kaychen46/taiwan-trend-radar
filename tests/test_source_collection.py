import os
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("LLM_API_KEY", "test-only-key")

import pipeline_mvp as radar


class Response:
    def __init__(self, status_code, content):
        self.status_code = status_code
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise radar.requests.HTTPError(f"HTTP {self.status_code}")


class SourceCollectionTests(unittest.TestCase):
    def test_stock_uses_official_atom_without_index_when_available(self):
        atom = f"""<feed xmlns="http://www.w3.org/2005/Atom">
          <entry><title>[新聞] 官方測試標題</title>
            <link href="https://www.ptt.cc/bbs/Stock/M.123.A.456.html" />
            <updated>{datetime.now(timezone.utc).isoformat()}</updated></entry>
        </feed>""".encode()

        def get(url, **kwargs):
            self.assertEqual(url, "https://www.ptt.cc/atom/Stock.xml")
            return Response(200, atom)

        with patch.object(radar.requests, "get", side_effect=get):
            signals, status = radar.fetch_ptt_recent(["Stock"])
        self.assertEqual(status, {"Stock": "available"})
        self.assertEqual(signals[0]["source"], "PTT_Stock")

    def test_stock_403_uses_only_recent_explicit_stock_index_entries(self):
        recent = format_datetime(datetime.now(timezone.utc))
        stale = format_datetime(datetime.now(timezone.utc) - timedelta(days=3))
        rss = f"""<rss><channel>
          <item><title>[新聞] 測試財經標題- 看板 Stock - ptt.cc</title>
            <link>https://news.google.com/rss/articles/stock-good?oc=5</link>
            <pubDate>{recent}</pubDate></item>
          <item><title>[新聞] 其他看板 - 看板 Gossiping - ptt.cc</title>
            <link>https://news.google.com/rss/articles/wrong-board?oc=5</link>
            <pubDate>{recent}</pubDate></item>
          <item><title>[新聞] 過期資料 - 看板 Stock - ptt.cc</title>
            <link>https://news.google.com/rss/articles/old?oc=5</link>
            <pubDate>{stale}</pubDate></item>
        </channel></rss>""".encode()

        def get(url, **kwargs):
            if url == "https://www.ptt.cc/atom/Stock.xml":
                return Response(403, b"blocked")
            if url == "https://news.google.com/rss/search":
                self.assertEqual(kwargs["params"]["q"], "site:ptt.cc/bbs/Stock when:1d")
                return Response(200, rss)
            self.fail(f"unexpected URL: {url}")

        with patch.object(radar.requests, "get", side_effect=get):
            signals, status = radar.fetch_ptt_recent(["Stock"])

        self.assertEqual(status, {"Stock": "indexed"})
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["source"], "PTT_Stock_索引")
        self.assertEqual(signals[0]["title"], "[新聞] 測試財經標題")
        self.assertEqual(signals[0]["url"], "https://news.google.com/rss/articles/stock-good?oc=5")

    def test_rss_parse_failure_is_reported_as_unavailable(self):
        source = {"name": "test-rss", "type": "search", "url": "https://example.com/rss"}
        broken = SimpleNamespace(entries=[], bozo=True, bozo_exception=ValueError("bad feed"))
        with patch.object(radar, "RSS_SOURCES", [source]), patch.object(radar.feedparser, "parse", return_value=broken):
            signals, status = radar.fetch_rss_signals()
        self.assertEqual(signals, [])
        self.assertEqual(status, {"test-rss": {"state": "unavailable", "count": 0}})

    def test_missing_youtube_key_is_visible_in_source_status(self):
        with patch.object(radar, "YOUTUBE_API_KEY", ""):
            signals, status = radar.fetch_youtube_trending_tw()
        self.assertEqual(signals, [])
        self.assertEqual(status, {"YouTube_TW發燒": {"state": "not_configured", "count": 0}})

    def test_indexed_source_title_is_not_claimed_as_original(self):
        signal = {"source": "PTT_Stock_索引", "title": "[新聞] 索引標題", "url": "https://news.google.com/rss/articles/stock-good?oc=5"}
        report = {"topic_name": "測試", "reference_urls": [signal["url"]]}
        verified = radar.verified_reports([report], [signal])
        self.assertEqual(verified[0]["sources_involved"], ["PTT_Stock_索引"])
        self.assertEqual(verified[0]["source_titles"], ["Google 新聞索引顯示：[新聞] 索引標題"])


if __name__ == "__main__":
    unittest.main()
