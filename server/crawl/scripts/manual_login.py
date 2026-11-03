"""手动有头登录：打开有界面浏览器，用户自行登录，成功后自动保存 Cookie 并关闭浏览器。

用法：
    python manual_login.py <platform_code> [--timeout 600]

流程：
    1) 打开有界面浏览器到该平台登录页
    2) 用户手动完成登录（扫码/账号/手机号均可）
    3) 轮询 Cookie，检测到登录态后保存 storage_state + cookie，自动关闭浏览器
    4) 状态写入 server/logs/login/manual_<code>.json，供后端查询

平台编码：jd / taobao / suning / pdd / amazon
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from proxy_util import playwright_proxy

CRAWL_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = CRAWL_DIR.parents[1]
COOKIES_DIR = CRAWL_DIR / "cookies"
STORAGE_DIR = CRAWL_DIR / "storage"
LOG_DIR = Path(__file__).resolve().parents[2] / "logs" / "login"

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(PROJECT_ROOT / "playwright-browsers"))

PC_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
    "Mobile/15E148 Safari/604.1"
)

PLATFORMS = {
    "jd": {
        "url": "https://passport.jd.com/uc/login",
        "cookies": ("pt_key", "pt_pin"),
        "host": "jd.com",
        "mobile": False,
    },
    "taobao": {
        "url": "https://login.taobao.com/havanaone/login/login.htm",
        "cookies": ("unb",),
        "host": "taobao.com",
        "mobile": False,
    },
    "suning": {
        "url": "https://passport.suning.com/ids/login",
        "cookies": ("sn", "sna", "snid", "snsession", "_snmd", "userId"),
        "host": "suning.com",
        "mobile": False,
    },
    "pdd": {
        "url": "https://mobile.yangkeduo.com/login.html",
        "cookies": ("PDDAccessToken", "PDDUserId", "pdd_user_id"),
        "host": "yangkeduo.com",
        "mobile": True,
    },
    "amazon": {
        "url": "https://www.amazon.com/gp/sign-in.html",
        "cookies": ("x-main", "session-token", "at-acb", "at-main"),
        "host": "amazon.com",
        "mobile": False,
    },
}


def _status_path(code: str) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR / f"manual_{code}.json"


def write_status(code: str, status: str, message=None, pid=None, started_at=None) -> None:
    payload = {
        "platform_code": code,
        "status": status,
        "message": message,
        "pid": pid,
        "started_at": started_at,
        "finished_at": (
            datetime.now().isoformat(timespec="seconds")
            if status in ("success", "failed")
            else None
        ),
    }
    try:
        _status_path(code).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


def _login_like_url(url: str) -> bool:
    u = (url or "").lower()
    return any(k in u for k in ("login", "passport", "signin", "sign-in", "/ap/", "verify"))


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("platform_code")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()

    code = args.platform_code.strip().lower()
    cfg = PLATFORMS.get(code)
    started_at = datetime.now().isoformat(timespec="seconds")
    if not cfg:
        write_status(code, "failed", f"未知平台: {code}", os.getpid(), started_at)
        print(json.dumps({"status": "failed", "error": f"unknown platform {code}"}))
        return

    write_status(code, "running", "请在浏览器中完成登录…", os.getpid(), started_at)

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        launch_kwargs = {"headless": False}
        browser = None
        # 优先系统 Chrome（更真实，登录成功率更高），失败回退内置 chromium
        try:
            browser = await p.chromium.launch(channel="chrome", **launch_kwargs)
        except Exception:  # noqa: BLE001
            browser = await p.chromium.launch(**launch_kwargs)

        proxy = playwright_proxy()
        extra = {"proxy": proxy} if proxy else {}
        if cfg.get("mobile"):
            context = await browser.new_context(
                user_agent=MOBILE_UA,
                viewport={"width": 390, "height": 844},
                is_mobile=True,
                has_touch=True,
                locale="zh-CN",
                **extra,
            )
        else:
            context = await browser.new_context(
                user_agent=PC_UA,
                viewport={"width": 1280, "height": 860},
                locale="zh-CN",
                **extra,
            )

        page = await context.new_page()
        try:
            await page.goto(cfg["url"], wait_until="domcontentloaded", timeout=60000)
        except Exception:  # noqa: BLE001
            pass

        deadline = asyncio.get_event_loop().time() + max(60, args.timeout)
        success = False
        while asyncio.get_event_loop().time() < deadline:
            if not browser.is_connected():
                break
            cookies_list = await context.cookies()
            cookies = {c["name"]: c["value"] for c in cookies_list}
            hit = any(k in cookies and cookies[k] for k in cfg["cookies"])
            # 兜底：已离开登录页且回到平台主站
            left_login = (cfg["host"] in (page.url or "")) and not _login_like_url(page.url)
            if hit or left_login:
                success = True
                break
            await asyncio.sleep(2)

        if success:
            cookies_list = await context.cookies()
            cookies = {c["name"]: c["value"] for c in cookies_list}
            COOKIES_DIR.mkdir(parents=True, exist_ok=True)
            STORAGE_DIR.mkdir(parents=True, exist_ok=True)
            (COOKIES_DIR / f"{code}.json").write_text(
                json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            storage = await context.storage_state()
            (STORAGE_DIR / f"{code}.json").write_text(
                json.dumps(storage, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            try:
                await browser.close()
            except Exception:  # noqa: BLE001
                pass
            write_status(code, "success", "登录成功，Cookie 已保存", os.getpid(), started_at)
            print(json.dumps({"status": "success", "platform_code": code}, ensure_ascii=False))
            return

        try:
            await browser.close()
        except Exception:  # noqa: BLE001
            pass
        write_status(code, "failed", "登录未完成或超时", os.getpid(), started_at)
        print(json.dumps({"status": "failed", "error": "login not completed"}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
