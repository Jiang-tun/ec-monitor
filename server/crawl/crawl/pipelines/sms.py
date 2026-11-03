"""接码结果回写管道：把 SmsResult 提交给后端内部接口。"""

import json
from urllib import request as urlrequest
from urllib.error import URLError

from scrapy.exceptions import DropItem

from crawl.items import SmsResult


class SmsResultPipeline:
    def open_spider(self, spider):
        settings = spider.crawler.settings
        self.api_base = (settings.get("INTERNAL_API_BASE") or "").rstrip("/")
        self.api_key = settings.get("NODE_API_KEY") or ""

    def process_item(self, item, spider):
        if not isinstance(item, SmsResult):
            return item

        payload = json.dumps(item.to_payload(), ensure_ascii=False).encode("utf-8")
        req = urlrequest.Request(
            f"{self.api_base}/internal/sms-results",
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
            spider.logger.error(
                "接码结果回写失败 order=%s: %s", item.order_id, exc
            )
            self._inc(spider, "sms/failed")
            raise DropItem(f"sms post failed: {exc}") from exc

        if body.get("code") != 0:
            spider.logger.error(
                "接码结果被拒绝 order=%s: %s",
                item.order_id,
                body.get("message"),
            )
            self._inc(spider, "sms/rejected")
            raise DropItem(f"sms rejected: {body.get('message')}")

        spider.logger.info(
            "接码回写成功 order=%s action=%s status=%s",
            item.order_id,
            item.action,
            item.status,
        )
        self._inc(spider, "sms/posted")
        return item

    @staticmethod
    def _inc(spider, key: str) -> None:
        stats = getattr(getattr(spider, "crawler", None), "stats", None)
        if stats is not None:
            stats.inc_value(key)
