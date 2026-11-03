"""搜索结果回写管道：把一份关键词列表批次 POST 给后端内部接口。"""

import json
from urllib import request as urlrequest
from urllib.error import URLError

from scrapy.exceptions import DropItem

from crawl.items import SearchBatch


class SearchResultPipeline:
    def open_spider(self, spider):
        settings = spider.crawler.settings
        self.api_base = (settings.get("INTERNAL_API_BASE") or "").rstrip("/")
        self.api_key = settings.get("NODE_API_KEY") or ""
        if not self.api_base:
            spider.logger.error("未配置 INTERNAL_API_BASE，搜索结果无法回写")

    def process_item(self, item, spider):
        if not isinstance(item, SearchBatch):
            return item

        payload = json.dumps(item.to_payload(), ensure_ascii=False).encode("utf-8")
        req = urlrequest.Request(
            f"{self.api_base}/internal/search-results",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-Node-Api-Key": self.api_key,
            },
            method="POST",
        )
        try:
            with urlrequest.urlopen(req, timeout=20) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except (URLError, TimeoutError, ValueError) as exc:
            spider.logger.error("搜索回写失败 task=%s: %s", item.task_id, exc)
            self._inc(spider, "search/failed")
            raise DropItem(f"search post failed: {exc}") from exc

        if body.get("code") != 0:
            spider.logger.error(
                "搜索回写被拒绝 task=%s: %s", item.task_id, body.get("message")
            )
            self._inc(spider, "search/rejected")
            raise DropItem(f"search rejected: {body.get('message')}")

        data = body.get("data") or {}
        spider.logger.info(
            "搜索回写成功 task=%s total=%s new=%s dup=%s",
            item.task_id,
            data.get("total"),
            data.get("new"),
            data.get("dup"),
        )
        self._inc(spider, "search/posted")
        return item

    @staticmethod
    def _inc(spider, key: str) -> None:
        stats = getattr(getattr(spider, "crawler", None), "stats", None)
        if stats is not None:
            stats.inc_value(key)
