"""淘宝/天猫 Spider（搜索列表 + 商品详情）。

- taobao_search：由后端 run_task 直连启动，读 -a keyword/limit/task_id/platform_id，
  产出 SearchBatch，经 SearchResultPipeline 回写候选表。
- taobao_detail：消费 ecom:sc:{site_group}:requests 采集种子，
  产出 CrawlItem，经 SnapshotPipeline 回写快照，前端「实时采集/商品详情」显示。

登录态（storage_state）读取 server/crawl/storage/taobao.json 或 taobao_state.json。
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
    for name in ("taobao.json", "taobao_state.json"):
        path = _STORAGE_DIR / name
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

class TaobaoSearchSpider(BaseRedisSpider):
    name = "taobao_search"
    platform_code = "taobao"

    def __init__(
        self,
        keyword: str = "",
        limit: str = "20",
        task_id: str = "",
        platform_id: str = "",
        site_group: str = "taobao",
        *args,
        **kwargs,
    ):
        self.keyword = (keyword or "").strip()
        self.limit = int(limit) if str(limit).isdigit() else 20
        self.task_id = task_id
        self.platform_id = int(platform_id) if str(platform_id).isdigit() else None
        super().__init__(site_group=site_group, *args, **kwargs)

    def start_requests(self):
        q = quote(self.keyword)
        url = (
            f"https://uland.taobao.com/sem/tbsearch?keyword={q}"
            f"&localImgKey=&page=1&q={q}&tab=all"
        )
        meta = {
            "playwright": True,
            # 淘宝页面连接不会进入 networkidle，用固定等待 + 滚动让价格异步渲染
            "playwright_page_methods": [
                PageMethod("wait_for_timeout", 6000),
                PageMethod(
                    "evaluate", "window.scrollTo(0, document.body.scrollHeight)"
                ),
                PageMethod("wait_for_timeout", 3000),
            ],
        }
        storage = _load_storage_state()
        if storage:
            meta["playwright_context_kwargs"] = {"storage_state": storage}
        apply_proxy(meta)
        yield scrapy.Request(url=url, callback=self.parse, meta=meta, dont_filter=True)

    def parse(self, response, **kwargs):
        cards = response.css("a[class*='CardV2--doubleCardWrapper']")
        if not cards:
            # 兜底：部分页面卡片 class 不同
            cards = response.css("a[class*='doubleCardWrapper'], [id^='item_id_']")

        items = []
        for card in cards[: self.limit]:
            href = card.css("::attr(href)").get() or ""
            raw_id = card.css("::attr(id)").get() or ""
            platform_item_id = self._extract_id(raw_id, href)
            if not platform_item_id:
                continue

            title = "".join(
                card.css("div[class*='Title--title'] span::text").getall()
            ).strip() or "".join(card.css("[class*='Title'] span::text").getall()).strip()

            price_int = card.css(
                "span[class*='Price--priceInt']::text"
            ).get(default="").strip()
            price_float = card.css(
                "span[class*='Price--priceFloat']::text"
            ).get(default="").strip()
            price = f"{price_int}{price_float}" if price_int else None
            if not price:
                # 兜底：从卡片文本里抓 "¥xxx.yy"
                card_text = "".join(card.css("::text").getall())
                m = re.search(r"[¥￥]\s*(\d+(?:\.\d+)?)", card_text)
                price = m.group(1) if m else None

            image = card.css("img::attr(src)").get() or card.css(
                "img::attr(data-src)"
            ).get()
            if image and image.startswith("//"):
                image = "https:" + image

            items.append(
                {
                    "platform_item_id": platform_item_id,
                    "title": title or None,
                    "url": href or None,
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
        # id 形如 item_id_1082579041881
        m = re.search(r"item_id[_\-]?(\d+)", raw_id or "")
        if m:
            return m.group(1)
        m = re.search(r"[?&](?:id|itemId|item_id)=(\d+)", href or "")
        if m:
            return m.group(1)
        m = re.search(r"(\d{6,})", raw_id or "")
        return m.group(1) if m else None


# ==================== 商品详情 ====================

class TaobaoDetailSpider(BaseRedisSpider):
    name = "taobao_detail"

    def __init__(self, site_group: str = "taobao", *args, **kwargs):
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
        if not any(k in url for k in ("taobao.com", "tmall.com")):
            self.logger.info("taobao_detail 跳过非淘宝种子: %s", url)
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
        blocked = ("login.taobao.com" in (response.url or "")) or (
            "亲，请登录" in page_title or "登录" in page_title and not text("[class*='mainTitle']::text")
        )

        title = pick(
            [
                "span[class*='mainTitle']::text",
                "[class*='ItemTitle--mainTitle']::text",
                "h1::text",
                "title::text",
            ]
        )

        price_value = pick(
            [
                "div[class*='highlightPrice'] .text--jyiUrkMu::text",
                "div[class*='highlightPrice'] span::text",
                "[class*='priceWrap'] [class*='price']::text",
                "[class*='Price--priceText']::text",
            ]
        )
        price_label = text("span[class*='title--xbzcSemP']::text")

        promo_tip = text("span[class*='priceTipTextPC']::text")
        countdown_parts = texts("div[class*='countDownWrap'] .text--lbinE_mM::text")
        countdown = " ".join(countdown_parts) if countdown_parts else None

        shipping = text("span[class*='shipping']::text")
        freight = text("span[class*='freight']::text")
        delivery_addr = text("div[class*='deliveryAddrWrap'] span::text")

        guarantees = texts("span[class*='guaranteeText']::text")
        pay_methods = texts("span[class*='payInfoItem']::text")

        series = text(
            "div[class*='Auctions'] div[class*='isSelected--B9kA08Lo'] "
            "span[class*='valueItemText--wn36aLIc']::text"
        )

        sku_groups = response.css("div[class*='skuItem--Z2AJB9Ew']")
        sku_data = []
        for group in sku_groups:
            group_name = group.css(
                "div[class*='ItemLabel'] span::text"
            ).get(default="").strip()
            options = []
            selected = None
            for opt in group.css("div[class*='valueItem--smR4pNt4']"):
                opt_text = opt.css(
                    "span[class*='valueItemText']::text"
                ).get(default="").strip()
                opt_vid = opt.css("::attr(data-vid)").get()
                is_selected = "isSelected" in (opt.css("::attr(class)").get() or "")
                disabled = opt.css("::attr(data-disabled)").get() == "true"
                options.append(
                    {"text": opt_text, "vid": opt_vid, "disabled": disabled}
                )
                if is_selected:
                    selected = opt_text
            sku_data.append(
                {"group": group_name, "selected": selected, "options": options}
            )

        color = next((g["selected"] for g in sku_data if "颜色" in g["group"]), None)
        capacity = next((g["selected"] for g in sku_data if "容量" in g["group"]), None)

        quantity_tip = text("div[class*='quantityTip']::text")
        quantity_default = response.css("input[class*='countValue']::attr(value)").get()

        detail = {
            "page_title": page_title,
            "blocked": blocked,
            "note": "淘宝/天猫需登录态或触发风控，暂无法展示商品信息" if blocked else None,
            "price_label": price_label,
            "promo_tip": promo_tip,
            "countdown": countdown,
            "shipping": shipping,
            "freight": freight,
            "delivery_address": delivery_addr,
            "guarantees": guarantees,
            "pay_methods": pay_methods,
            "series": series,
            "color": color,
            "capacity": capacity,
            "sku_groups": sku_data,
            "quantity_tip": quantity_tip,
            "quantity_default": quantity_default,
        }

        yield CrawlItem(
            item_id=seed.get("db_id"),
            platform_item_id=seed.get("item_id"),
            price=_to_float(price_value),
            title=title,
            url=seed.get("url") or response.url,
            page_status=403 if blocked else response.status,
            price_basis=seed.get("price_basis"),
            strategy_used="browser",
            platform_id=seed.get("platform_id"),
            task_id=seed.get("task_id"),
            snapshot_time=datetime.now(),
            promotion_json={"taobao_detail": detail},
        )
