"""京东关键词搜索列表 Spider（re.jd.com，Playwright 渲染）。

由后端 run_task 以直连模式启动：
    scrapy crawl jd_search -a site_group=cn-main -a task_id=... \
        -a keyword=... -a platform_id=... -a limit=20

产出一条 SearchBatch，由 SearchResultPipeline 回写 /internal/search-results，
后端写候选表，前端「关键词采集」完成后弹确认列表。
"""

import html
import json
import re
from datetime import datetime
from urllib.parse import quote

import scrapy
from scrapy_playwright.page import PageMethod

from crawl.items import CrawlItem, SearchBatch
from crawl.proxy import apply_proxy
from crawl.spiders.base import BaseRedisSpider


class JdSearchSpider(BaseRedisSpider):
    name = "jd_search"
    platform_code = "jd"

    def __init__(
        self,
        keyword: str = "",
        limit: str = "20",
        task_id: str = "",
        platform_id: str = "",
        site_group: str = "cn-main",
        *args,
        **kwargs,
    ):
        self.keyword = (keyword or "").strip()
        self.limit = int(limit) if str(limit).isdigit() else 20
        self.task_id = task_id
        self.platform_id = int(platform_id) if str(platform_id).isdigit() else None
        super().__init__(site_group=site_group, *args, **kwargs)

    def start_requests(self):
        url = "https://re.jd.com/search?keyword=" + quote(self.keyword)
        meta = {
            "playwright": True,
            "playwright_page_methods": [
                # 等待商品卡片渲染完成（re.jd.com 是 SPA）
                PageMethod(
                    "wait_for_selector", ".jd-pick-content-item", timeout=20000
                ),
                PageMethod("wait_for_timeout", 2000),
            ],
        }
        apply_proxy(meta)
        yield scrapy.Request(
            url=url,
            callback=self.parse,
            meta=meta,
            dont_filter=True,
        )

    def parse(self, response, **kwargs):
        cards = response.css(".jd-pick-content-item")
        items = []

        for card in cards[: self.limit]:
            # 首选：img 的 data-item 是一段 HTML 转义 JSON，含 id/title/price/imageUrl/landUrl/shopName
            data_item_raw = card.css("img::attr(data-item)").get()
            data = {}
            if data_item_raw:
                try:
                    data = json.loads(html.unescape(data_item_raw))
                except (ValueError, TypeError):
                    data = {}

            land_url = data.get("landUrl") or data.get("click") or ""
            platform_item_id = self._extract_item_id(land_url, data)
            # 去重必填：拿不到商品ID的卡片直接跳过
            if not platform_item_id:
                continue

            # 标题：优先 data-item.title，其次 DOM，再次图片 alt
            title = (data.get("title") or "").strip()
            if not title:
                title = "".join(
                    card.css(".title-text-wrapper span::text").getall()
                ).strip()
            if not title:
                title = (card.css("img::attr(alt)").get() or "").strip()

            # 价格：优先 data-item.price（如 "198.00"），其次 DOM 整数/小数拼接
            price = data.get("price")
            if not price:
                price_int = card.css(".price-int::text").get(default="").strip()
                price_dec = card.css(".price-decimal::text").get(default="").strip()
                price = f"{price_int}{price_dec}" if price_int else None

            # 主图：data-item.imageUrl 是 jfs/... 相对路径，补全京东图床域名
            image = data.get("imageUrl") or card.css("img::attr(src)").get()
            if image and not image.startswith("http"):
                image = "https://img14.360buyimg.com/n1/" + image.lstrip("/")

            items.append(
                {
                    "platform_item_id": platform_item_id,
                    "title": title or None,
                    "url": land_url or None,
                    "price": price,
                    "image": image or None,
                }
            )

        yield SearchBatch(
            task_id=self.task_id,
            platform_id=self.platform_id,
            platform_code=self.platform_code,
            keyword=self.keyword,
            items=items,
        )

    @staticmethod
    def _extract_item_id(land_url: str, data: dict) -> str | None:
        # 1) data-item 里的商品ID（id / skuId / wareId ...）
        for key in ("id", "skuId", "wareId", "itemId", "productId"):
            val = data.get(key)
            if val is not None and str(val).isdigit():
                return str(val)
        # 2) 从商品链接里取：.../100012043978.html 或 ?sku=xxx&wareId=xxx
        if land_url:
            m = re.search(r"/(\d+)\.html", land_url) or re.search(
                r"[?&](?:sku|skuId|wareId|itemId|productId)=(\d+)", land_url
            )
            if m:
                return m.group(1)
        return None


class JdDetailSpider(BaseRedisSpider):
    """京东商品详情 Spider（消费 ecom:sc:{site_group}:requests 的采集种子）。

    由「立即采集 / 定时调度」投递种子触发，产出 CrawlItem，
    由 SnapshotPipeline 回写 /internal/snapshots，前端「实时采集」显示。
    """

    name = "jd_detail"

    def __init__(self, site_group: str = "jd", *args, **kwargs):
        super().__init__(site_group=site_group, *args, **kwargs)

    @staticmethod
    def _load_storage_state():
        """读取登录态 storage_state（crawl/storage/jd.json），用于绕过频控/登录墙。"""
        from pathlib import Path

        base = Path(__file__).resolve().parents[2] / "storage"
        path = base / "jd.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
        return None

    def make_request_from_data(self, data):
        try:
            text = (
                data.decode(self.redis_encoding or "utf-8")
                if isinstance(data, (bytes, bytearray))
                else str(data)
            )
            seed = json.loads(text)
        except (TypeError, ValueError):
            return []
        if not isinstance(seed, dict):
            return []
        url = seed.get("url") or ""
        if "jd.com" not in url:
            self.logger.info("jd_detail 跳过非京东种子: %s", url)
            return []
        meta = dict(seed)
        meta["playwright"] = True
        meta["handle_httpstatus_all"] = True
        # 带登录态，降低频控概率
        storage = self._load_storage_state()
        if storage:
            meta["playwright_context_kwargs"] = {"storage_state": storage}
        # 注意：不要把 wait_for_selector 放进 page_methods（元素不存在会直接抛错使请求失败），
        # 只用固定等待 + 滚动，然后交给 parse 用多套兜底选择器解析。
        meta["playwright_page_methods"] = [
            PageMethod("wait_for_timeout", 3500),
            PageMethod("evaluate", "window.scrollTo(0, 600)"),
            PageMethod("wait_for_timeout", 1500),
        ]
        apply_proxy(meta)
        return [scrapy.Request(url, callback=self.parse, meta=meta, dont_filter=True)]

    def parse(self, response, **kwargs):
        seed = response.meta

        def text(selector, default=None):
            vals = response.css(selector).getall()
            for v in vals:
                if v and v.strip():
                    return v.strip()
            return default

        def pick(selectors, default=None):
            for sel in selectors:
                val = text(sel)
                if val:
                    return val
            return default

        def texts(selector):
            return [t.strip() for t in response.css(selector).getall() if t.strip()]

        page_title = (response.css("title::text").get() or "").strip()
        blocked = ("pf.jd.com" in (response.url or "")) or ("频控" in page_title)

        title = pick(
            [
                ".sku-title-name::text",
                ".sku-name::text",
                ".itemInfo-wrap .sku-name::text",
                "h1::text",
                ".product-title::text",
            ]
        )
        price_current = pick(
            [
                ".product-price--value::text",
                ".p-price .price::text",
                ".summary-price .price::text",
                ".price::text",
            ]
        )
        price_original = pick(
            [
                ".product-price--gray span:first-child::text",
                ".p-price .price-origin::text",
                "del::text",
                ".origin-price::text",
            ]
        )

        comment_count = text(".product-price-panel--options-comment-count::text")
        ranking = text(".ranking-name::text")

        enjoyed = texts(".shareds .floor-item div::text")
        enjoy_more = texts(".again-shareds .floor-item div::text")

        delivery_time = text(".logistics-delivery-time::text")
        address = text(".jd_area_text_wBZaLGYG::text")
        logistics = text(".logistics-service-name::text")

        series = text(
            ".specification-series-item--selected .specification-series-item-text::text"
        )
        color = text(
            ".specification-group-0 .specification-item-sku--selected "
            ".specification-item-sku-text::text"
        )
        capacity = text(
            ".specification-group-1 .specification-item-sku--selected "
            ".specification-item-sku-text::text"
        )
        purchase_type = text(
            ".specification-group-2 .specification-item-sku--selected "
            ".specification-item-sku-text::text"
        )

        service_tags = texts(
            ".service-support-tag-item a::text, "
            ".service-support-tag-item .service-support-tag-item--text::text"
        )
        service_tags = [t for t in service_tags if t and t != "·"]

        services = []
        for group in response.css(".service-list"):
            name = group.css(".service-list-name::text").get(default="").strip()
            for item in group.css(".service-item"):
                svc_name = item.css(".service-name::text").get(default="").strip()
                svc_price = item.css(".service-price::text").get(default="").strip()
                if svc_name:
                    services.append(
                        {"group": name, "name": svc_name, "price": svc_price}
                    )

        detail = {
            "page_title": page_title,
            "blocked": blocked,
            "note": "京东频控/需登录态，暂无法展示商品信息" if blocked else None,
            "comment_count": comment_count,
            "ranking": ranking,
            "enjoyed_discounts": enjoyed,
            "available_discounts": enjoy_more,
            "delivery_time": delivery_time,
            "address": address,
            "logistics": logistics,
            "series": series,
            "color": color,
            "capacity": capacity,
            "purchase_type": purchase_type,
            "service_tags": service_tags,
            "optional_services": services,
        }

        yield CrawlItem(
            item_id=seed.get("db_id"),
            platform_item_id=seed.get("item_id"),
            price=self._to_float(price_current),
            original_price=self._to_float(price_original),
            title=title,
            url=seed.get("url") or response.url,
            # 频控页统一记 403，便于前端辨识与后续下架判定区分
            page_status=403 if blocked else response.status,
            price_basis=seed.get("price_basis"),
            strategy_used="browser",
            platform_id=seed.get("platform_id"),
            task_id=seed.get("task_id"),
            snapshot_time=datetime.now(),
            promotion_json={"jd_detail": detail},
        )

    @staticmethod
    def _to_float(value):
        if not value:
            return None
        m = re.search(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
        return float(m.group()) if m else None