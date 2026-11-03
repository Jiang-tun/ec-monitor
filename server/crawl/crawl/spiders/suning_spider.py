"""苏宁易购 Spider（搜索列表 + 商品详情）。

- suning_search：后端 run_task 直连启动，读 -a keyword/limit/task_id/platform_id，
  产出 SearchBatch，经 SearchResultPipeline 回写候选表。
- suning_detail：消费 ecom:sc:{site_group}:requests 采集种子，
  产出 CrawlItem，经 SnapshotPipeline 回写快照，前端「实时采集/商品详情」显示。

登录态（可选）读取 server/crawl/storage/suning.json。
"""

import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import scrapy
from scrapy_playwright.page import PageMethod

from crawl.items import CrawlItem, SearchBatch
from crawl.proxy import apply_proxy
from crawl.spiders.base import BaseRedisSpider

_STORAGE_DIR = Path(__file__).resolve().parents[2] / "storage"


def _load_storage_state():
    path = _STORAGE_DIR / "suning.json"
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

class SuningSearchSpider(BaseRedisSpider):
    name = "suning_search"
    platform_code = "suning"

    def __init__(
        self,
        keyword: str = "",
        limit: str = "20",
        task_id: str = "",
        platform_id: str = "",
        site_group: str = "suning",
        *args,
        **kwargs,
    ):
        self.keyword = (keyword or "").strip()
        self.limit = int(limit) if str(limit).isdigit() else 20
        self.task_id = task_id
        self.platform_id = int(platform_id) if str(platform_id).isdigit() else None
        super().__init__(site_group=site_group, *args, **kwargs)

    def start_requests(self):
        url = f"https://search.suning.com/{quote(self.keyword)}/"
        meta = {
            "playwright": True,
            # 不用致命 wait_for_selector；固定等待 + 滚动触发渲染
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
        cards = response.css("ul.general.clearfix > li.item-wrap")
        if not cards:
            cards = response.css("li.item-wrap")

        items = []
        for li in cards[: self.limit]:
            # 只认真实商品链接（.../<数字>.html），避免广告跳转链接把店铺ID当商品ID
            hrefs = li.css("a::attr(href)").getall()
            link = next(
                (h for h in hrefs if h and re.search(r"/(\d+)\.html", h)), None
            )
            if not link:
                continue
            if link.startswith("//"):
                link = "https:" + link

            m_id = re.search(r"/(\d+)\.html", link)
            platform_item_id = m_id.group(1) if m_id else None
            if not platform_item_id:
                continue

            title = "".join(
                t.strip() for t in li.css(".title-selling-point a::text").getall() if t.strip()
            )
            price_text = "".join(
                li.css(".def-price *::text").getall()
                + li.css(".def-price::text").getall()
            )
            m = re.search(r"(\d+(?:\.\d+)?)", price_text)
            price = m.group(1) if m else None

            image = li.css("img::attr(src)").get() or li.css("img::attr(data-src)").get()
            if image and image.startswith("//"):
                image = "https:" + image

            items.append(
                {
                    "platform_item_id": platform_item_id,
                    "title": title or None,
                    "url": link or None,
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
    def _extract_id(raw_id: str, href: str) -> str | None:
        if href:
            m = re.search(r"/(\d+)\.html", href)
            if m:
                return m.group(1)
        m = re.search(r"(\d{6,})", raw_id or "")
        return m.group(1) if m else None


# ==================== 商品详情 ====================

class SuningDetailSpider(BaseRedisSpider):
    name = "suning_detail"

    def __init__(self, site_group: str = "suning", *args, **kwargs):
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
        if "suning.com" not in url:
            self.logger.info("suning_detail 跳过非苏宁种子: %s", url)
            return []

        meta = dict(seed)
        meta["playwright"] = True
        meta["handle_httpstatus_all"] = True
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

        def pick(selectors, default=None):
            for sel in selectors:
                val = text(sel)
                if val:
                    return val
            return default

        def texts(selector):
            return [t.strip() for t in response.css(selector).getall() if t and t.strip()]

        page_title = (response.css("title::text").get() or "").strip()
        blocked = ("passport.suning.com" in (response.url or "")) or (
            "请登录" in page_title
        )

        title = pick(
            [
                "#itemDisplayName .line:last-child::text",
                "#itemDisplayName::text",
                "h1::text",
                "title::text",
            ]
        )
        selling_point = text("#promotionDesc .line::text")

        activity_price = text(".mainprice::text")
        subsidy_price = text(".arrival-price-txt::text")

        comment_count = text(".proinfo-comments span::text")

        coupons = texts(".p-quan2 .p-quan-white::text")

        promotions = []
        for li in response.css(".promo-list li[id]"):
            style = li.css("::attr(style)").get() or ""
            if "display:none" in style:
                continue
            label = li.css("label::text").get(default="").strip()
            content = "".join(li.css(".promotion-content *::text").getall()).strip() or li.css(
                ".promotion-content::text"
            ).get(default="").strip()
            if label or content:
                promotions.append({"label": label, "content": content})

        province = text("#provinceName::text")
        city = text("#citybName::text")
        district = text("#districtName::text")
        address = f"{province or ''}{city or ''}{district or ''}"
        stock_status = text("#haveProduct::text")
        freight = text("#c_kucun a::text")
        delivery_time = text("#prescription::text")
        supplier = text("#shopName::text")
        weight = text("#weightcvalue::text")

        sku_groups = []
        for dl in response.css("#colorItemList, #versionItemList"):
            group_name = dl.css("dt .w2::text").get(default="").strip()
            options = []
            selected = None
            for li in dl.css("dd li"):
                classes = li.css("::attr(class)").get() or ""
                opt = {
                    "title": li.css("::attr(title)").get(),
                    "sku": li.css("::attr(sku)").get(),
                    "selected": "selected" in classes,
                    "disabled": "disabled" in classes,
                }
                options.append(opt)
                if opt["selected"]:
                    selected = opt["title"]
            if group_name or options:
                sku_groups.append(
                    {"group": group_name, "selected": selected, "options": options}
                )

        services = []
        for li in response.css("#yanbao .mulita"):
            span_text = li.css(".promotionSpan::text").get(default="").strip()
            if span_text:
                services.append(span_text)

        service_tags = texts(".pro-serv-panel .icon-image::text")

        detail = {
            "page_title": page_title,
            "blocked": blocked,
            "note": "苏宁需登录态或触发风控，暂无法展示商品信息" if blocked else None,
            "selling_point": selling_point,
            "activity_price": activity_price,
            "subsidy_price": subsidy_price,
            "comment_count": comment_count,
            "coupons": coupons,
            "promotions": promotions,
            "delivery_address": address,
            "stock_status": stock_status,
            "freight": freight,
            "delivery_time": delivery_time,
            "supplier": supplier,
            "weight": weight,
            "sku_groups": sku_groups,
            "value_added_services": services,
            "service_tags": service_tags,
        }

        yield CrawlItem(
            item_id=seed.get("db_id"),
            platform_item_id=seed.get("item_id"),
            price=_to_float(activity_price or subsidy_price),
            title=title,
            url=seed.get("url") or response.url,
            page_status=403 if blocked else response.status,
            price_basis=seed.get("price_basis"),
            strategy_used="browser",
            platform_id=seed.get("platform_id"),
            task_id=seed.get("task_id"),
            snapshot_time=datetime.now(),
            promotion_json={"suning_detail": detail},
        )
