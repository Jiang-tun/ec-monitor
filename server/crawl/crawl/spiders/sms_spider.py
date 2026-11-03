"""接码平台 Spider（scrapy-redis 队列版）。

后端把接码任务推入 ``ecom:sc:sms:{provider_code}``，字段：
  {"action":"acquire","order_id":1,"provider_id":4,"provider_code":"smsnam","platform_id":3}
  {"action":"fetch_code","order_id":1,"provider_code":"smsnam","code_url":"https://..."}

Spider 解析后通过 SmsResultPipeline 回写 ``POST /internal/sms-results``。

启动（常驻消费）：
    scrapy crawl smsnam -a site_group=default
"""

import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from lxml import html as lxml_html
from scrapy import Request

from crawl.items import SmsResult
from crawl.spiders.base import BaseRedisSpider


# 平台编码 -> 接码页面短信发送方关键词（从公共免费号里挑出目标平台的验证码）
PLATFORM_CODE_KEYWORDS = {
    "jd": "京东|JD",
    "taobao": "淘宝|阿里|Taobao",
    "pdd": "拼多多|PDD",
    "1688": "1688|阿里巴巴",
}


class BaseSmsSpider(BaseRedisSpider):
    provider_code = ""
    acquire_url = ""
    code_wait_ms = 6000

    def __init__(
        self,
        site_group: str = "default",
        order_id: str = "",
        action: str = "",
        code_url: str = "",
        *args,
        **kwargs,
    ):
        self.manual_order_id = int(order_id) if str(order_id).isdigit() else 0
        self.manual_action = action
        self.manual_code_url = code_url
        super().__init__(site_group=site_group, *args, **kwargs)
        self.redis_key = f"ecom:sc:sms:{self.provider_code}"

    async def start(self):
        if self.manual_order_id and self.manual_action in ("acquire", "fetch_code"):
            req = self._build_request(
                {
                    "action": self.manual_action,
                    "order_id": self.manual_order_id,
                    "provider_code": self.provider_code,
                    "code_url": self.manual_code_url,
                }
            )
            if req is not None:
                yield req
            return
        async for req in super().start():
            yield req

    # ---------- 队列种子 → Request ----------

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
        seed.setdefault("provider_code", self.provider_code)
        return self._build_request(seed) or []

    def _build_request(self, seed: dict):
        action = seed.get("action")
        if action not in ("acquire", "fetch_code"):
            return None

        meta = dict(seed)
        meta["dont_filter"] = True

        if action == "fetch_code":
            url = seed.get("code_url")
            if not url:
                return None
            meta["handle_httpstatus_all"] = True
        else:
            url = self.acquire_url
            meta["playwright"] = False

        return Request(url, callback=self.parse, meta=meta, dont_filter=True)

    # ---------- 解析 ----------

    def parse(self, response):
        action = response.meta.get("action")
        try:
            order_id = int(response.meta.get("order_id") or 0)
        except (TypeError, ValueError):
            order_id = 0
        if not order_id:
            self.logger.error("接码种子缺少 order_id: %s", response.url)
            return

        if action == "acquire":
            return list(self.parse_acquire(response, order_id))
        return [
            self.parse_code(
                response,
                order_id,
                response.meta.get("code_url"),
                response.meta.get("platform_code"),
            )
        ]

    def parse_acquire(self, response, order_id: int):
        wraps = response.xpath('//div[contains(@class,"tgme_widget_message_wrap")]')
        self.logger.info("接码取号：候选消息 %d 条", len(wraps))

        for wrap in reversed(wraps):
            marker = " ".join(
                wrap.xpath(
                    './/div[contains(@class,"tgme_widget_message_text")]//text()'
                ).getall()
            )
            phone = wrap.xpath(".//tg-spoiler//text()").get()
            links = wrap.xpath(".//a/@href").getall()
            code_url = next(
                (
                    html.unescape(href)
                    for href in links
                    if href.startswith("http") and "t.me" not in href
                ),
                None,
            )
            if not phone or not code_url or "Next" not in marker:
                continue

            phone_clean = re.sub(r"[^\d+]", "", phone)
            if not phone_clean:
                continue
            yield SmsResult(
                order_id=order_id,
                action="acquire",
                status="success",
                phone=phone_clean,
                code_url=code_url,
                raw={
                    "phone_raw": phone,
                    "marker": marker[:200],
                    "code_url": code_url,
                },
            )
            return

        yield SmsResult(
            order_id=order_id,
            action="acquire",
            status="failed",
            error="暂无可接号码（未找到 Next number in / 手机号 / 接码链接）",
        )

    def parse_code(self, response, order_id: int, code_url=None, platform_code=None):
        title = (response.xpath("//title/text()").get() or "").strip()
        blocked = response.status == 403 or any(
            marker in title
            for marker in ("Just a moment", "请稍候", "安全验证", "Attention Required")
        )

        if blocked:
            return self._fetch_code_via_scrapling(order_id, code_url, platform_code)

        rows = response.xpath(
            '//div[contains(@class,"num-grid__table")]//tbody/tr'
        )
        if not rows:
            rows = response.xpath("//table//tbody/tr")
        if not rows:
            return SmsResult(
                order_id=order_id,
                action="fetch_code",
                status="pending",
                code_url=code_url,
                raw={"note": "接码页面未就绪", "title": title},
            )

        text = " ".join(rows[0].xpath("./td[1]//text()").getall()).strip()
        received_at = " ".join(
            rows[0].xpath("./td[2]//text()").getall()
        ).strip()
        code = self._extract_code(text)

        if not code:
            return SmsResult(
                order_id=order_id,
                action="fetch_code",
                status="pending",
                code_url=code_url,
                raw={"note": "暂未匹配到验证码", "text": text[:200], "time": received_at},
            )

        return SmsResult(
            order_id=order_id,
            action="fetch_code",
            status="success",
            code=code,
            code_url=code_url,
            raw={"text": text[:500], "time": received_at},
        )

    # ---------- scrapling 兜底（绕过 Cloudflare 5 秒盾） ----------

    @staticmethod
    def _extract_code(text: str):
        if not text:
            return None
        match = re.search(r"(?<!\d)(\d{4,8})(?!\d)", text)
        return match.group(1) if match else None

    def _fetch_code_via_scrapling(self, order_id: int, code_url=None, platform_code=None):
        """通过独立子进程调用 scrapling（过 Cloudflare 5 秒盾，避免与 Twisted 循环冲突）。"""
        if not code_url:
            return SmsResult(
                order_id=order_id,
                action="fetch_code",
                status="failed",
                error="缺少接码页面地址，请重新获取手机号",
            )

        script = Path(__file__).resolve().parents[2] / "scripts" / "scrapling_fetch.py"
        executable = self._scrapling_executable() or ""
        keyword = PLATFORM_CODE_KEYWORDS.get((platform_code or "").lower(), "")
        cmd = [sys.executable, str(script), code_url]

        env = os.environ.copy()
        if executable:
            env["SMS_SCRAPLING_EXECUTABLE"] = executable
        if keyword:
            env["SMS_CODE_KEYWORD"] = keyword

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=300,
                env=env,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.error("scrapling 子进程失败: %s", exc)
            return SmsResult(
                order_id=order_id,
                action="fetch_code",
                status="failed",
                code_url=code_url,
                error=f"scrapling 子进程失败: {type(exc).__name__}",
            )

        lines = [line for line in (proc.stdout or "").strip().splitlines() if line.strip()]
        if not lines:
            stderr = (proc.stderr or "").strip()[-300:]
            self.logger.error("scrapling 无输出: %s", stderr)
            return SmsResult(
                order_id=order_id,
                action="fetch_code",
                status="failed",
                code_url=code_url,
                error=f"scrapling 无输出: {stderr[:200] or 'unknown'}",
            )

        try:
            data = json.loads(lines[-1])
        except ValueError:
            return SmsResult(
                order_id=order_id,
                action="fetch_code",
                status="failed",
                code_url=code_url,
                error="scrapling 输出不是合法 JSON",
            )

        status = data.get("status")
        if status == "success" and data.get("code"):
            return SmsResult(
                order_id=order_id,
                action="fetch_code",
                status="success",
                code=str(data["code"]),
                code_url=code_url,
                raw={
                    "text": data.get("text"),
                    "time": data.get("time"),
                    "via": "scrapling",
                },
            )
        if status == "failed":
            return SmsResult(
                order_id=order_id,
                action="fetch_code",
                status="failed",
                code_url=code_url,
                error=(data.get("error") or "scrapling 抓取失败")[:512],
            )
        return SmsResult(
            order_id=order_id,
            action="fetch_code",
            status="pending",
            code_url=code_url,
            raw={"note": data.get("note") or "暂未获取到验证码", **data},
        )

    def _scrapling_executable(self):
        import os

        explicit = os.environ.get("SMS_SCRAPLING_EXECUTABLE")
        if explicit and Path(explicit).exists():
            return explicit
        browser_root = Path(__file__).resolve().parents[4] / "playwright-browsers"
        # scrapling 自带 playwright 期望 chromium-1217，优先使用
        preferred = browser_root / "chromium-1217" / "chrome-win64" / "chrome.exe"
        if preferred.exists():
            return str(preferred)
        candidates = sorted(
            browser_root.glob("chromium-*/chrome-win64/chrome.exe"),
        )
        return str(candidates[0]) if candidates else None


class SmsNamSpider(BaseSmsSpider):
    """SMSNam（Telegram 公开号源）。"""

    name = "smsnam"
    provider_code = "smsnam"
    acquire_url = "https://t.me/s/smsnam"