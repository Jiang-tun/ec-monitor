"""淘宝（Taobao）短信登录 Playwright 脚本（全自动·接码联动）。

目标登录页：https://login.taobao.com/havanaone/login/login.htm

完整闭环（推荐）
----------------
    1) 以“采集节点”身份调用内部接口取号（平台 taobao，走 SMSNam）
    2) 打开无头浏览器 → 切到「短信登录」→ 填入手机号
    3) 点击淘宝「获取验证码」，触发淘宝给该手机号发短信
    4) 调用内部接口触发接码平台取码，轮询拿到验证码
    5) 回填验证码、勾选协议并提交登录
    6) 检测到 unb/cookie2 即成功，保存 Cookie/storage_state

用法
----
    python login_taobao.py --platform-code taobao --headless
    python login_taobao.py --order-id 12 --login-id 5 --headless
    python login_taobao.py --verify-only
    python login_taobao.py --dry-run
    python login_taobao.py --phone 13800000000 --code 123456

环境变量
--------
    INTERNAL_API_BASE   默认 http://127.0.0.1:8000
    NODE_API_KEY        默认 dev-node-api-key

落盘
----
    server/crawl/cookies/taobao.json   # name -> value
    server/crawl/storage/taobao.json   # Playwright storage_state（taobao 详情/搜索复用）
    server/logs/login/taobao_*.png     # 失败/验证截图
"""

import argparse
import asyncio
import json
import os
import sys
import urllib.request
from pathlib import Path

CRAWL_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = CRAWL_DIR.parents[1]
COOKIES_DIR = CRAWL_DIR / "cookies"
STORAGE_DIR = CRAWL_DIR / "storage"
LOG_DIR = CRAWL_DIR.parent / "logs" / "login"

LOGIN_URL = "https://login.taobao.com/havanaone/login/login.htm"

API_BASE = os.environ.get("INTERNAL_API_BASE", "http://127.0.0.1:8000").rstrip("/")
NODE_KEY = os.environ.get("NODE_API_KEY", "dev-node-api-key")

# 淘宝登录成功关键 Cookie（unb=用户ID，cookie2 并存）
AUTH_COOKIES = ("unb",)

SMS_TAB_SELECTORS = ["a.sms-login-tab-item", "text=短信登录"]
PHONE_SELECTORS = ["#fm-sms-login-id", 'input[placeholder*="手机"]']
CODE_SELECTORS = ["#fm-smscode", 'input[placeholder*="验证码"]']
GET_CODE_SELECTORS = ["a.send-btn-link", ".send-btn", "text=获取验证码"]
LOGIN_BTN_SELECTORS = [
    "button.fm-submit.sms-login",
    "button:has-text('登录')",
    ".fm-btn",
]
SLIDER_SELECTORS = [".nc-container", "#nc_1_wrapper", ".nc_iconfont", "[id^='nc_']"]


# ==================== 内部接口客户端 ====================

def _api(method: str, path: str, payload: dict | None = None) -> dict:
    url = f"{API_BASE}{path}"
    data = None
    headers = {"X-Node-Api-Key": NODE_KEY}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def api_acquire(platform_code: str) -> dict:
    body = _api("POST", "/internal/sms-orders", {"platform_code": platform_code})
    if body.get("code") != 0:
        raise RuntimeError(f"取号失败: {body.get('message')}")
    return body["data"]


def api_get_order(order_id: int) -> dict:
    body = _api("GET", f"/internal/sms-orders/{order_id}")
    if body.get("code") != 0:
        raise RuntimeError(f"查询订单失败: {body.get('message')}")
    return body["data"]


def api_fetch_code(order_id: int) -> dict:
    body = _api("POST", f"/internal/sms-orders/{order_id}/fetch-code")
    if body.get("code") != 0:
        raise RuntimeError(f"触发取码失败: {body.get('message')}")
    return body["data"]


def api_post_login_result(login_id: int, status: str, cookies=None, storage=None, error=None) -> None:
    payload = {"login_id": login_id, "status": status}
    if status == "success":
        payload["cookies"] = cookies
        payload["storage_state"] = storage
    else:
        payload["error"] = (error or "登录失败")[:512]
    try:
        _api("POST", "/internal/login-results", payload)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] 回写登录结果失败: {exc}", file=sys.stderr)


async def wait_phone(order_id: int, timeout_s: int = 180) -> dict:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        order = await asyncio.to_thread(api_get_order, order_id)
        status = order.get("status")
        if order.get("phone") and status in ("number_ready", "code_ready", "logging"):
            return order
        if status in ("failed", "cancelled", "expired"):
            raise RuntimeError(f"取号失败(状态={status}): {order.get('error')}")
        await asyncio.sleep(2)
    raise RuntimeError("等待手机号超时")


async def wait_code(order_id: int, timeout_s: int = 180) -> str:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_s
    last_trigger = -999.0
    while loop.time() < deadline:
        order = await asyncio.to_thread(api_get_order, order_id)
        if order.get("sms_code"):
            return str(order["sms_code"])
        if order.get("status") in ("failed", "cancelled", "expired"):
            raise RuntimeError(f"取码失败(状态={order.get('status')}): {order.get('error')}")
        now = loop.time()
        if now - last_trigger >= 20:
            try:
                await asyncio.to_thread(api_fetch_code, order_id)
            except Exception as exc:  # noqa: BLE001
                print(f"[warn] 触发取码: {exc}", file=sys.stderr)
            last_trigger = now
        await asyncio.sleep(4)
    raise RuntimeError("等待验证码超时")


# ==================== Playwright 工具 ====================

def _browsers_path() -> None:
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(PROJECT_ROOT / "playwright-browsers"))


async def _first_visible(page, selectors, timeout_ms: int = 8000):
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            await loc.wait_for(state="visible", timeout=timeout_ms)
            return loc
        except Exception:  # noqa: BLE001
            continue
    return None


async def _screenshot(page, name: str) -> str:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"{name}.png"
    try:
        await page.screenshot(path=str(path), full_page=False)
    except Exception:  # noqa: BLE001
        return ""
    return str(path)


async def _robust_click(locator) -> None:
    try:
        await locator.click(timeout=4000)
        return
    except Exception:  # noqa: BLE001
        pass
    try:
        await locator.evaluate("el => el.click()")
    except Exception:  # noqa: BLE001
        pass


async def detect_slider(page) -> bool:
    for sel in SLIDER_SELECTORS:
        try:
            if await page.locator(sel).first.is_visible(timeout=800):
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


async def switch_to_sms_login(page) -> bool:
    tab = await _first_visible(page, SMS_TAB_SELECTORS, timeout_ms=6000)
    if tab is not None:
        try:
            await tab.click()
            await page.wait_for_timeout(800)
        except Exception:  # noqa: BLE001
            pass
    phone_input = await _first_visible(page, PHONE_SELECTORS, timeout_ms=6000)
    return phone_input is not None


async def detect_cookies(context) -> dict:
    cookies = await context.cookies()
    return {c["name"]: c["value"] for c in cookies}


async def wait_login_success(context, page, timeout_s: int = 180) -> dict | None:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        cookies = await detect_cookies(context)
        if all(k in cookies and cookies[k] for k in AUTH_COOKIES):
            return cookies
        await asyncio.sleep(2)
    return None


async def save_state(context, platform_code: str) -> tuple[dict, dict]:
    cookies = await detect_cookies(context)
    COOKIES_DIR.mkdir(parents=True, exist_ok=True)
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    (COOKIES_DIR / f"{platform_code}.json").write_text(
        json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    storage = await context.storage_state()
    (STORAGE_DIR / f"{platform_code}.json").write_text(
        json.dumps(storage, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return cookies, storage


def _digits(phone: str) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    # 淘宝短信登录是 +86 大陆号；去 +86 前缀
    if len(digits) == 13 and digits.startswith("86"):
        digits = digits[2:]
    return digits


async def select_country_code(page, phone_raw: str) -> tuple[str | None, str]:
    """按带国际区号的手机号，在淘宝地区下拉里选中对应地区。

    返回 (selected_code, local_number)：
      - "+85244969505" -> ("+852", "44969505")
      - 无 "+" 前缀（默认 +86）-> (None, digits)
    淘宝地区下拉是原生 <select name="nativePhoneCodeSelector">，
    option 文本形如 "+852 中国香港"，value 为 JSON（含 phoneCode）。
    """
    raw = (phone_raw or "").strip()
    digits = _digits(raw)
    if not raw.startswith("+"):
        return None, digits

    intl = "+" + "".join(ch for ch in raw if ch.isdigit())
    sel = page.locator("select.native-phone-code-select")
    if await sel.count() == 0:
        sel = page.locator('select[name="nativePhoneCodeSelector"]')
    if await sel.count() == 0:
        return None, digits

    options = await page.evaluate(
        """() => {
            const s = document.querySelector('select.native-phone-code-select')
                   || document.querySelector('select[name="nativePhoneCodeSelector"]');
            if (!s) return [];
            return [...s.options].map(o => ({ text: o.text, value: o.value }));
        }"""
    )

    best = None
    for o in options:
        code = ""
        try:
            v = json.loads(o["value"])
            code = "+" + str(v.get("phoneCode", ""))
        except Exception:  # noqa: BLE001
            m = re.match(r"(\+\d+)", o.get("text") or "")
            code = m.group(1) if m else ""
        if code and intl.startswith(code):
            if best is None or len(code) > len(best["code"]):
                best = {"code": code, "text": o["text"]}

    if best:
        try:
            await sel.select_option(label=best["text"])
            await page.wait_for_timeout(300)
            return best["code"], intl[len(best["code"]):]
        except Exception:  # noqa: BLE001
            pass
    return None, digits


async def _accept_agreement(page) -> None:
    """勾选“已阅读并同意…”协议（淘宝短信登录提交前必须勾选）。"""
    try:
        cb = page.locator("#fm-agreement-checkbox")
        if await cb.count():
            try:
                if await cb.is_checked():
                    return
            except Exception:  # noqa: BLE001
                pass
            # 优先点文字标签，其次强制点 checkbox
            try:
                await page.get_by_text("已阅读并同意", exact=False).first.click(timeout=2000)
                return
            except Exception:  # noqa: BLE001
                pass
            try:
                await cb.click(force=True, timeout=2000)
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass


# ==================== 主流程 ====================

async def run(args) -> dict:
    from playwright.async_api import async_playwright

    _browsers_path()
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    order: dict | None = None
    if not args.verify_only and not args.dry_run and not args.phone:
        if args.order_id:
            order = await wait_phone(args.order_id, timeout_s=args.wait_timeout)
        else:
            created = await asyncio.to_thread(api_acquire, args.platform_code)
            order_id = created["id"]
            print(f"[info] 已创建接码订单 #{order_id}，等待手机号…", file=sys.stderr)
            order = await wait_phone(order_id, timeout_s=args.wait_timeout)
        args.order_id = order["id"]

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=args.headless)
        from proxy_util import playwright_proxy

        proxy = playwright_proxy()
        context = await browser.new_context(
            locale="zh-CN",
            viewport={"width": 1366, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            **({"proxy": proxy} if proxy else {}),
        )
        page = await context.new_page()
        await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(2500)

        existing = await detect_cookies(context)
        if all(k in existing and existing[k] for k in AUTH_COOKIES):
            cookies, storage = await save_state(context, args.platform_code)
            await browser.close()
            return {
                "status": "success",
                "platform_code": args.platform_code,
                "order_id": args.order_id,
                "already_logged_in": True,
                "cookies": cookies,
                "cookie_map": cookies,
                "storage_state": storage,
                "url": page.url,
            }

        ok = await switch_to_sms_login(page)
        if not ok:
            shot = await _screenshot(page, "taobao_sms_tab_fail")
            await browser.close()
            return {
                "status": "failed",
                "error": "未找到短信登录页签或手机号输入框",
                "screenshot": shot,
                "url": page.url,
            }

        if args.verify_only:
            shot = await _screenshot(page, "taobao_sms_verified")
            await browser.close()
            return {
                "status": "success",
                "verify_only": True,
                "message": "已成功切换到短信登录表单",
                "screenshot": shot,
                "url": page.url,
            }

        phone_raw = args.phone or (order.get("phone") if order else "")
        if not phone_raw:
            shot = await _screenshot(page, "taobao_no_phone")
            await browser.close()
            return {"status": "failed", "error": "无可用手机号（未取号且未提供 --phone）", "screenshot": shot}

        # 按国际区号选择地区（+852 中国香港 / +86 中国大陆 …）
        country_code, phone = await select_country_code(page, phone_raw)

        phone_input = await _first_visible(page, PHONE_SELECTORS)
        if phone_input is None:
            shot = await _screenshot(page, "taobao_phone_input_fail")
            await browser.close()
            return {"status": "failed", "error": "未找到手机号输入框", "screenshot": shot}
        await phone_input.fill(phone)

        if args.dry_run:
            code_input = await _first_visible(page, CODE_SELECTORS)
            get_code = await _first_visible(page, GET_CODE_SELECTORS, timeout_ms=3000)
            login_btn = await _first_visible(page, LOGIN_BTN_SELECTORS, timeout_ms=3000)
            shot = await _screenshot(page, "taobao_dry_run")
            await browser.close()
            return {
                "status": "success",
                "dry_run": True,
                "phone_raw": phone_raw,
                "country_code": country_code,
                "local_phone": phone,
                "phone_input": True,
                "code_input": code_input is not None,
                "get_code_btn": get_code is not None,
                "login_btn": login_btn is not None,
                "screenshot": shot,
                "url": page.url,
            }

        # 点击获取验证码
        if args.auto_send:
            get_code = await _first_visible(page, GET_CODE_SELECTORS, timeout_ms=5000)
            if get_code is not None:
                await _robust_click(get_code)
                await page.wait_for_timeout(1500)
        slider = await detect_slider(page)
        await _screenshot(page, "taobao_after_send_code")

        # 取验证码
        if args.code:
            code = args.code
        elif args.order_id:
            print(f"[info] 触发接码平台取码（订单 #{args.order_id}）…", file=sys.stderr)
            code = await wait_code(args.order_id, timeout_s=args.wait_timeout)
        else:
            if args.headless:
                await browser.close()
                return {"status": "failed", "error": "缺少取码来源：需 --order-id 或 --code"}
            try:
                code = input("请输入收到的短信验证码后回车：").strip()
            except EOFError:
                code = ""
        if not code:
            await browser.close()
            return {"status": "failed", "error": "未获取到验证码", "slider": slider}

        code_input = await _first_visible(page, CODE_SELECTORS)
        if code_input is None:
            shot = await _screenshot(page, "taobao_code_input_fail")
            await browser.close()
            return {"status": "failed", "error": "未找到验证码输入框", "screenshot": shot}
        await code_input.fill(code)

        # 勾选协议并提交
        await _accept_agreement(page)
        await page.wait_for_timeout(300)
        login_btn = await _first_visible(page, LOGIN_BTN_SELECTORS, timeout_ms=4000)
        if login_btn is not None:
            await _robust_click(login_btn)

        cookies = await wait_login_success(context, page, timeout_s=args.timeout)
        if not cookies:
            shot = await _screenshot(page, "taobao_login_fail")
            await browser.close()
            if args.login_id:
                await asyncio.to_thread(
                    api_post_login_result, args.login_id, "failed", None, None,
                    "登录超时：未检测到 unb，可能有滑块/图片验证码或验证码错误",
                )
            return {
                "status": "failed",
                "error": "登录超时：未检测到 unb，可能存在滑块/图片验证码或验证码错误",
                "slider": slider,
                "screenshot": shot,
                "url": page.url,
            }

        cookies, storage = await save_state(context, args.platform_code)
        await browser.close()

        if args.login_id:
            await asyncio.to_thread(
                api_post_login_result, args.login_id, "success", cookies, storage, None
            )

        return {
            "status": "success",
            "platform_code": args.platform_code,
            "order_id": args.order_id,
            "phone": phone_raw,
            "cookies": cookies,
            "cookie_map": cookies,
            "storage_state": storage,
            "url": page.url,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="淘宝短信登录 Playwright 脚本（接码联动）")
    parser.add_argument("--platform-code", default="taobao", help="平台编码（取号用），默认 taobao")
    parser.add_argument("--order-id", type=int, default=0, help="已有接码订单 ID（跳过取号）")
    parser.add_argument("--login-id", type=int, default=0, help="登录会话 ID（成功后回写 /internal/login-results）")
    parser.add_argument("--phone", default="", help="手工手机号（调试用，传了则不取号）")
    parser.add_argument("--code", default="", help="手工验证码（调试用，传了则不取码）")
    parser.add_argument("--verify-only", action="store_true", help="只验证短信登录入口并截图")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="填充手机号并校验控件，不发短信/不提交")
    parser.add_argument("--auto-send", dest="auto_send", action="store_true", default=True, help="自动点击获取验证码（默认开）")
    parser.add_argument("--no-auto-send", dest="auto_send", action="store_false", help="不自动点击获取验证码")
    parser.add_argument("--headless", action="store_true", help="无头模式")
    parser.add_argument("--timeout", type=int, default=180, help="等待登录成功秒数")
    parser.add_argument("--wait-timeout", type=int, default=180, help="等待取号/取码秒数")
    args = parser.parse_args()

    try:
        result = asyncio.run(run(args))
    except Exception as exc:  # noqa: BLE001
        result = {"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
