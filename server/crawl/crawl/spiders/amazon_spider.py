"""亚马逊 Spider（搜索列表 + 商品详情）。

- amazon_search：后端 run_task 直连启动，读 -a keyword/limit/task_id/platform_id，
  产出 SearchBatch（asin 作为 platform_item_id），经 SearchResultPipeline 回写候选表。
- amazon_detail：消费 ecom:sc:{site_group}:requests 采集种子，
  产出 CrawlItem，经 SnapshotPipeline 回写快照，前端「实时采集/商品详情」显示。

登录态（可选）读取 server/crawl/storage/amazon.json。
"""

import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

import scrapy
from scrapy_playwright.page import PageMethod

from crawl.items import CrawlItem, SearchBatch
from crawl.proxy import apply_proxy
from crawl.spiders.base import BaseRedisSpider

_STORAGE_DIR = Path(__file__).resolve().parents[2] / "storage"


def _load_storage_state():
    path = _STORAGE_DIR / "amazon.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    return None


def _to_float(value):
    if not value:
        return None
    m = re.search(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(m.group()) if m else None


# ==================== 搜索列表 ====================

class AmazonSearchSpider(BaseRedisSpider):
    name = "amazon_search"
    platform_code = "amazon"

    def __init__(
        self,
        keyword: str = "",
        limit: str = "20",
        task_id: str = "",
        platform_id: str = "",
        site_group: str = "amazon",
        *args,
        **kwargs,
    ):
        self.keyword = (keyword or "").strip()
        self.limit = int(limit) if str(limit).isdigit() else 20
        self.task_id = task_id
        self.platform_id = int(platform_id) if str(platform_id).isdigit() else None
        super().__init__(site_group=site_group, *args, **kwargs)

    def start_requests(self):
        url = f"https://www.amazon.com/s?k={quote_plus(self.keyword)}"
        meta = {
            "playwright": True,
            "playwright_page_goto_kwargs": {
                "wait_until": "domcontentloaded",
                "timeout": 60000,
            },
            "playwright_page_methods": [
                PageMethod("wait_for_timeout", 4000),
                PageMethod("evaluate", "window.scrollTo(0, 800)"),
                PageMethod("wait_for_timeout", 2000),
            ],
        }
        storage = _load_storage_state()
        if storage:
            meta["playwright_context_kwargs"] = {"storage_state": storage}
        apply_proxy(meta)
        yield scrapy.Request(url=url, callback=self.parse, meta=meta, dont_filter=True)

    def parse(self, response, **kwargs):
        results = response.css('[data-component-type="s-search-result"]')
        items = []
        for it in results[: self.limit]:
            asin = (it.attrib.get("data-asin") or "").strip()
            if not asin:
                continue
            link = it.css("h2 a::attr(href)").get()
            url = response.urljoin(link) if link else f"https://www.amazon.com/dp/{asin}"
            title_parts = it.css("h2 a span::text").getall() or it.css(
                "h2 span::text"
            ).getall()
            title = "".join(t.strip() for t in title_parts if t.strip())
            title = title.replace("Amazon Renewed", "").strip()
            price = _to_float(it.css(".a-price .a-offscreen::text").get())
            image = it.css("img.s-image::attr(src)").get()
            items.append(
                {
                    "platform_item_id": asin,
                    "title": title or None,
                    "url": url,
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


# ==================== 商品详情 ====================

class AmazonDetailSpider(BaseRedisSpider):
    name = "amazon_detail"

    def __init__(self, site_group: str = "amazon", *args, **kwargs):
        super().__init__(site_group=site_group, *args, **kwargs)

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
        if "amazon." not in url:
            self.logger.info("amazon_detail 跳过非亚马逊种子: %s", url)
            return []

        meta = dict(seed)
        meta["playwright"] = True
        meta["handle_httpstatus_all"] = True
        meta["playwright_page_goto_kwargs"] = {
            "wait_until": "domcontentloaded",
            "timeout": 60000,
        }
        storage = _load_storage_state()
        if storage:
            meta["playwright_context_kwargs"] = {"storage_state": storage}
        meta["playwright_page_methods"] = [
            PageMethod("wait_for_timeout", 4000),
            PageMethod("evaluate", "window.scrollTo(0, 800)"),
            PageMethod("wait_for_timeout", 2000),
        ]
        apply_proxy(meta)
        return [scrapy.Request(url, callback=self.parse, meta=meta, dont_filter=True)]

    def parse(self, response, **kwargs):
        seed = response.meta

        def text(selector, default=None):
            for v in response.css(selector).getall():
                if v and v.strip():
                    return v.strip()
            return default

        page_title = (response.css("title::text").get() or "").strip()
        body_head = " ".join(response.css("body ::text").getall()[:200])
        blocked = (
            "validateCaptcha" in (response.url or "")
            or "Robot Check" in page_title
            or "Enter the characters you see below" in body_head
        )

        title = text("#productTitle::text")
        byline = text("#bylineInfo::text")
        rating = text("#acrPopover::attr(title)")
        reviews = text("#acrCustomerReviewText::text")
        is_renewed = bool(response.css(".refurbished-badge"))
        bought = text(
            "#social-proofing-faceout-title-tk_bought .a-text-bold::text"
        )
        price = (
            text("#corePriceDisplay_desktop_feature_div .a-price .a-offscreen::text")
            or text("#corePrice_feature_div .a-price .a-offscreen::text")
            or text("#priceblock_ourprice::text")
            or text("#priceblock_dealprice::text")
            or text(".a-price .a-offscreen::text")
        )
        list_price = (
            text(".apex-basisprice-value .a-offscreen::text")
            or text(".basisPrice .a-offscreen::text")
            or text(".a-text-price .a-offscreen::text")
        )
        discount = text(".savingsPercentage::text")
        availability = text("#availability .a-color-price::text")
        sold_by = text("#sellerProfileTriggerId::text")
        ships_from = text(
            "#fulfillerInfoFeature_feature_div .offer-display-feature-text-message::text"
        )
        selected_color = text(
            "#inline-twister-expanded-dimension-text-color_name::text"
        )
        selected_size = text(
            "#inline-twister-expanded-dimension-text-size_name::text"
        )
        selected_provider = text(
            "#inline-twister-expanded-dimension-text-service_provider::text"
        )
        selected_grade = text(
            "#inline-twister-expanded-dimension-text-product_grade::text"
        )

        detail = {
            "page_title": page_title,
            "blocked": blocked,
            "note": "亚马逊触发人机验证/需登录态，暂无法展示商品信息" if blocked else None,
            "byline": byline,
            "rating": rating,
            "reviews": reviews,
            "is_renewed": is_renewed,
            "bought_recently": bought,
            "discount": discount,
            "availability": availability,
            "sold_by": sold_by,
            "ships_from": ships_from,
            "selected_color": selected_color,
            "selected_size": selected_size,
            "selected_service_provider": selected_provider,
            "selected_product_grade": selected_grade,
            "list_title": seed.get("list_title"),
            "is_sponsored": seed.get("is_sponsored"),
        }

        yield CrawlItem(
            item_id=seed.get("db_id"),
            platform_item_id=seed.get("item_id"),
            price=_to_float(price),
            original_price=_to_float(list_price),
            title=title,
            url=seed.get("url") or response.url,
            page_status=403 if blocked else response.status,
            price_basis=seed.get("price_basis"),
            strategy_used="browser",
            platform_id=seed.get("platform_id"),
            task_id=seed.get("task_id"),
            snapshot_time=datetime.now(),
            promotion_json={"amazon_detail": detail},
        )
