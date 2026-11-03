"""平台登录态（Cookie）检查与“用户手动有头登录”进程管理。"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.core.config import get_settings

settings = get_settings()

_SERVER_DIR = Path(__file__).resolve().parents[2]
_CRAWL_DIR = _SERVER_DIR / "crawl"
_COOKIES_DIR = _CRAWL_DIR / "cookies"
_STORAGE_DIR = _CRAWL_DIR / "storage"
_LOGIN_LOG_DIR = _SERVER_DIR / "logs" / "login"

# 平台编码 -> 登录页（仅用于校验/文档）
LOGIN_URLS = {
    "jd": "https://passport.jd.com/uc/login",
    "taobao": "https://login.taobao.com/havanaone/login/login.htm",
    "suning": "https://passport.suning.com/ids/login",
    "pdd": "https://mobile.yangkeduo.com/login.html",
    "amazon": "https://www.amazon.com/gp/sign-in.html",
}


def _status_path(platform_code: str) -> Path:
    _LOGIN_LOG_DIR.mkdir(parents=True, exist_ok=True)
    return _LOGIN_LOG_DIR / f"manual_{platform_code}.json"


def _pid_alive(pid: int) -> bool:
    if not pid:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
        return str(pid) in out
    except Exception:  # noqa: BLE001
        return False


def cookie_status(platform_code: str) -> dict:
    """检查平台登录态文件是否存在（storage 优先，其次 cookies）。"""
    code = (platform_code or "").strip().lower()
    if not code:
        return {"exists": False, "platform_code": code}
    for base, kind in ((_STORAGE_DIR, "storage"), (_COOKIES_DIR, "cookies")):
        path = base / f"{code}.json"
        if path.exists():
            try:
                mtime = datetime.fromtimestamp(path.stat().st_mtime).isoformat(
                    timespec="seconds"
                )
            except OSError:
                mtime = None
            return {
                "exists": True,
                "platform_code": code,
                "kind": kind,
                "path": str(path),
                "updated_at": mtime,
            }
    return {"exists": False, "platform_code": code}


def manual_status(platform_code: str) -> dict:
    code = (platform_code or "").strip().lower()
    path = _status_path(code)
    data: dict = {"platform_code": code, "status": "idle"}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {"platform_code": code, "status": "idle"}
    # 进程已退但状态仍是 running -> 判为失败
    if data.get("status") == "running" and not _pid_alive(int(data.get("pid") or 0)):
        data["status"] = "failed"
        data.setdefault("message", "登录进程已退出")
    data["cookie"] = cookie_status(code)
    return data


def start_manual_login(platform_code: str) -> dict:
    """启动有头浏览器供用户手动登录（子进程，成功后自动保存 Cookie 并关闭）。"""
    code = (platform_code or "").strip().lower()
    if code not in LOGIN_URLS:
        raise ValueError(f"不支持的平台: {code}")

    current = manual_status(code)
    if current.get("status") == "running":
        return {"started": True, "already_running": True, "pid": current.get("pid")}

    _LOGIN_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = _LOGIN_LOG_DIR / f"manual_{code}.log"

    script = _CRAWL_DIR / "scripts" / "manual_login.py"
    cmd = [sys.executable, str(script), code]

    env = os.environ.copy()
    env["INTERNAL_API_BASE"] = os.environ.get(
        "INTERNAL_API_BASE", "http://127.0.0.1:8000"
    )
    env["NODE_API_KEY"] = settings.node_api_key
    env["PYTHONIOENCODING"] = "utf-8"

    flags = 0x00000200 | 0x08000000 if os.name == "nt" else 0  # 新进程组 + 无窗口

    try:
        with open(log_path, "ab") as log_file:
            proc = subprocess.Popen(
                cmd,
                cwd=str(_CRAWL_DIR),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=env,
                creationflags=flags,
            )
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"启动登录进程失败: {type(exc).__name__}") from exc

    # 预写 running（脚本启动后会再写一次带 pid 的）
    try:
        _status_path(code).write_text(
            json.dumps(
                {
                    "platform_code": code,
                    "status": "running",
                    "message": "正在打开浏览器…",
                    "pid": proc.pid,
                    "started_at": datetime.now().isoformat(timespec="seconds"),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass

    return {"started": True, "pid": proc.pid, "log": str(log_path)}
