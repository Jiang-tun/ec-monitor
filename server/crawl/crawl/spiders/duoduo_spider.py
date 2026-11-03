"""拼多多 Spider（搜索列表 + 商品详情）。

- pdd_search：后端 run_task 直连启动，读 -a keyword/limit/task_id/platform_id，
  产出 SearchBatch，经 SearchResultPipeline 回写候选表。
- pdd_detail：消费 ecom:sc:{site_group}:requests 采集种子，
  产出 CrawlItem，经 SnapshotPipeline 回写快照，前端「实时采集/商品详情」显示。

拼多多移动端对 UA 敏感，使用移动端上下文（iPhone UA + 触屏）。
登录态（可选）读取 server/crawl/storage/pdd.json。
"""

import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import scrapy
from scrapy_playwright.page import PageMethod

from crawl.items import CrawlItem, SearchBatch
from crawl.spiders.base import BaseRedisSpider

_STORAGE_DIR = Path(__file__).resolve().parents[2] / "storage"

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
    "Mobile/15E148 Safari/604.1"
)


def _mobile_context_kwargs() -> dict:
    kwargs = {
        "user_agent": MOBILE_UA,
        "viewport": {"width": 390, "height": 844},
        "is_mobile": True,
        "has_touch": True,
        "locale": "zh-CN",
    }
    path = _STORAGE_DIR / "pdd.json"
    if path.exists():
        try:
            kwargs["storage_state"] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    from crawl.proxy import playwright_proxy

    proxy = playwright_proxy()
    if proxy:
        kwargs["proxy"] = proxy
    return kwargs


def _to_float(value):
    if value is None:
        return None
    m = re.search(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(m.group()) if m else None


# ==================== 搜索列表 ====================

class PddSearchSpider(BaseRedisSpider):
    name = "pdd_search"
    platform_code = "pdd"

    def __init__(
        self,
        keyword: str = "",
        limit: str = "20",
        task_id: str = "",
        platform_id: str = "",
        site_group: str = "pdd",
        *args,
        **kwargs,
    ):
        self.keyword = (keyword or "").strip()
        self.limit = int(limit) if str(limit).isdigit() else 20
        self.task_id = task_id
        self.platform_id = int(platform_id) if str(platform_id).isdigit() else None
        super().__init__(site_group=site_group, *args, **kwargs)

    def start_requests(self):
        url = (
            "https://mobile.yangkeduo.com/search_result.html?search_key="
            + quote(self.keyword)
        )
        meta = {
            "playwright": True,
            "playwright_context_kwargs": _mobile_context_kwargs(),
            "playwright_page_methods": [
                PageMethod("wait_for_timeout", 4000),
                PageMethod("evaluate", "window.scrollTo(0, document.body.scrollHeight)"),
                PageMethod("wait_for_timeout", 2500),
            ],
        }
        yield scrapy.Request(url=url, callback=self.parse, meta=meta, dont_filter=True)

    def parse(self, response, **kwargs):
        cards = response.css("div[data-uniqid]")
        if not cards:
            cards = response.css("div[data-goods-id], a[href*='goods_id=']")

        items = []
        for card in cards[: self.limit]:
            raw = card.get() or ""
            m = (
                re.search(r"goods_id=(\d+)", raw)
                or re.search(r"data-goods-id=[\"']?(\d+)", raw)
                or re.search(r"/goods\d*\.html\?goods_id=(\d+)", raw)
            )
            platform_item_id = m.group(1) if m else None
            if not platform_item_id:
                continue

            title = "".join(
                t.strip() for t in card.css("._3ANzdjkc ::text").getall() if t.strip()
            )
            if not title:
                title = "".join(
                    t.strip()
                    for t in card.css("[class*='title'] ::text").getall()
                    if t.strip()
                )

            price = _to_float(
                card.css("._3_U04GgA span:last-child::text").get()
            )
            if price is None:
                price = _to_float("".join(card.css("::text").getall()))

            image = card.css("img::attr(src)").get() or card.css(
                "img::attr(data-src)"
            ).get()

            items.append(
                {
                    "platform_item_id": platform_item_id,
                    "title": title or None,
                    "url": f"https://mobile.yangkeduo.com/goods.html?goods_id={platform_item_id}",
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

class PddDetailSpider(BaseRedisSpider):
    name = "pdd_detail"

    def __init__(self, site_group: str = "pdd", *args, **kwargs):
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
        if "yangkeduo.com" not in url and "pinduoduo.com" not in url:
            self.logger.info("pdd_detail 跳过非拼多多种子: %s", url)
            return []

        meta = dict(seed)
        meta["playwright"] = True
        meta["handle_httpstatus_all"] = True
        meta["playwright_context_kwargs"] = _mobile_context_kwargs()
        meta["playwright_page_methods"] = [
            PageMethod("wait_for_timeout", 4000),
            PageMethod("evaluate", "window.scrollTo(0, 700)"),
            PageMethod("wait_for_timeout", 2000),
        ]
        return [scrapy.Request(url, callback=self.parse, meta=meta, dont_filter=True)]

    def parse(self, response, **kwargs):
        seed = response.meta
        container = response.css(".goods-container-v2")

        def text(selector, default=None):
            for v in response.css(selector).getall():
                if v and v.strip():
                    return v.strip()
            return default

        def texts(selector):
            return [t.strip() for t in response.css(selector).getall() if t and t.strip()]

        page_title = (response.css("title::text").get() or "").strip()
        blocked = ("login" in (response.url or "")) or ("验证" in page_title) or (
            "captcha" in (response.url or "").lower()
        )

        carousel_images = []
        for img in container.css(".PPuOGFfM img"):
            src = img.attrib.get("src") or img.attrib.get("data-src")
            if src and src not in carousel_images:
                carousel_images.append(src)

        current_price = container.css(".kxqW0mMz span::text").get()
        price_symbol = container.css(".ENky5yyX span::text").get(default="¥")
        coupon_hint = container.css(".KM4qx8ua::text").get()
        coupon_text = container.css(".LER5I_0l::text").get()

        title = container.css(".tLYIg_Ju.enable-select span::text").get()
        if not title:
            title = text("title::text")
        ship_note = container.css(".gZOawjMB::text").get()

        badges = []
        for b in container.css(".yIixFf_t.kupzZmFx"):
            t = "".join(x.strip() for x in b.css("::text").getall() if x.strip())
            if t:
                badges.append(t)

        service_guarantees = []
        for g in container.css(".APMC25VO::text, .V4p5Hpg5 span::text"):
            t = g.strip()
            if t and t not in service_guarantees:
                service_guarantees.append(t)

        extra_services = [
            s.strip() for s in container.css(".KDFIGUNK::text").getall() if s.strip()
        ]

        official_cert = container.css(".XUIqdPbs::text").get()
        insurance = container.css(".vW3vkYfo::text").get()

        review_list = []
        for rev in container.css(".PiG41WVa"):
            user = rev.css(".jAtk8yRf::text").get()
            content = rev.css(".BMUTYZnz::text").get()
            if content:
                review_list.append({"user": user, "content": content.strip()})

        brand_block_texts = [
            t.strip()
            for t in container.css(".y2UnKSYI ::text").getall()
            if t.strip()
        ]

        specs = {}
        for row in container.css(".iUUH2sOQ"):
            key = row.css(".rMnkPxwx::text").get()
            val = row.css(".KjtdjVU2::text").get()
            if key and val:
                specs[key.strip()] = val.strip()

        detail_images = []
        for img in container.css(".Blmqu2TV img"):
            src = img.attrib.get("src") or img.attrib.get("data-src")
            if src and src not in detail_images:
                detail_images.append(src)

        sku_selected = container.css(".Mbx2m60G::text").get()
        sku_price = container.css(".ujEqGzEB::text").get()

        detail = {
            "page_title": page_title,
            "blocked": blocked,
            "note": "拼多多需登录态或触发风控，暂无法展示商品信息" if blocked else None,
            "coupon_hint": coupon_hint,
            "coupon_text": coupon_text,
            "ship_note": ship_note,
            "badges": badges,
            "service_guarantees": service_guarantees,
            "extra_services": extra_services,
            "official_cert": official_cert,
            "insurance": insurance,
            "review_list": review_list,
            "brand_block_texts": brand_block_texts,
            "specs": specs,
            "carousel_images": carousel_images,
            "detail_images": detail_images,
            "sku_selected": sku_selected,
            "sku_price": sku_price,
        }

        yield CrawlItem(
            item_id=seed.get("db_id"),
            platform_item_id=seed.get("item_id"),
            price=_to_float(current_price),
            title=title,
            url=seed.get("url") or response.url,
            page_status=403 if blocked else response.status,
            price_basis=seed.get("price_basis"),
            strategy_used="browser",
            platform_id=seed.get("platform_id"),
            task_id=seed.get("task_id"),
            snapshot_time=datetime.now(),
            promotion_json={"pdd_detail": detail},
        )
