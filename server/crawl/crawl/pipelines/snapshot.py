"""采集快照回写管道：把 CrawlItem 批量 POST 给后端 /internal/snapshots。"""

import json
import uuid
from urllib import request as urlrequest
from urllib.error import URLError

from scrapy.exceptions import DropItem

from crawl.items import CrawlItem


class SnapshotPipeline:
    def open_spider(self, spider):
        settings = spider.crawler.settings
        self.api_base = (settings.get("INTERNAL_API_BASE") or "").rstrip("/")
        self.api_key = settings.get("NODE_API_KEY") or ""
        if not self.api_base:
            spider.logger.error("未配置 INTERNAL_API_BASE，快照无法回写")

    def process_item(self, item, spider):
        if not isinstance(item, CrawlItem):
            return item

        payload = item.to_payload()
        body = {"batch_id": uuid.uuid4().hex, "items": [payload]}
        req = urlrequest.Request(
            f"{self.api_base}/internal/snapshots",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Node-Api-Key": self.api_key,
            },
            method="POST",
        )
        try:
            with urlrequest.urlopen(req, timeout=25) as resp:
                resp_body = json.loads(resp.read().decode("utf-8"))
        except (URLError, TimeoutError, ValueError) as exc:
            spider.logger.error(
                "快照回写失败 item=%s: %s", payload.get("item_id"), exc
            )
            self._inc(spider, "snapshot/failed")
            raise DropItem(f"snapshot post failed: {exc}") from exc

        if resp_body.get("code") != 0:
            spider.logger.error(
                "快照被拒绝 item=%s: %s",
                payload.get("item_id"),
                resp_body.get("message"),
            )
            self._inc(spider, "snapshot/rejected")
            raise DropItem(f"snapshot rejected: {resp_body.get('message')}")

        data = resp_body.get("data") or {}
        spider.logger.info(
            "快照回写成功 item=%s accepted=%s dup=%s changes=%s",
            payload.get("item_id"),
            data.get("accepted"),
            data.get("duplicates"),
            data.get("changes_detected"),
        )
        self._inc(spider, "snapshot/posted")
        return item

    @staticmethod
    def _inc(spider, key: str) -> None:
        stats = getattr(getattr(spider, "crawler", None), "stats", None)
        if stats is not None:
            stats.inc_value(key)
