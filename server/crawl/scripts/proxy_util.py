"""脚本侧读取后端启用的代理（Redis: proxy:active）。"""

import json
import os

from redis import Redis


def _redis_url() -> str:
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    if "protocol=" not in url:
        url += ("&" if "?" in url else "?") + "protocol=2"
    return url


def playwright_proxy():
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
