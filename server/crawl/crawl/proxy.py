"""读取后端启用的代理（Redis: proxy:active），供 Playwright 使用。"""

import json
import os

from redis import Redis


def _redis_url() -> str:
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    if "protocol=" not in url:
        url += ("&" if "?" in url else "?") + "protocol=2"
    return url


def playwright_proxy():
    """返回 Playwright 代理配置 dict，无启用代理则 None。"""
    try:
        r = Redis.from_url(_redis_url())
        raw = r.get("proxy:active")
        if not raw:
            return None
        d = json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)
        server = d.get("server")
        if not server:
            return None
        proxy = {"server": server}
        if d.get("username"):
            proxy["username"] = d["username"]
        if d.get("password"):
            proxy["password"] = d["password"]
        return proxy
    except Exception:  # noqa: BLE001
        return None


def apply_proxy(meta: dict) -> dict:
    """把当前启用代理合并进请求 meta 的 playwright_context_kwargs。"""
    proxy = playwright_proxy()
    if proxy:
        kwargs = meta.setdefault("playwright_context_kwargs", {})
        kwargs["proxy"] = proxy
    return meta
