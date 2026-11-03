"""用 scrapling 过 Cloudflare 5 秒盾并抓取接码页面，提取验证码，供 sms_spider 子进程调用。

用法：
    SMS_CODE_KEYWORD="京东|JD" python scrapling_fetch.py <code_url>

    - 浏览器路径读环境变量 SMS_SCRAPLING_EXECUTABLE，为空则自动探测项目内
      playwright-browsers（优先 chromium-1217）
    - 关键词读环境变量 SMS_CODE_KEYWORD，用于过滤短信发送方；为空则取最新带验证码的短信

输出：最后一行 JSON
    {"status": "success|pending|failed", "code": "1234", "text": "...", "time": "...", "error": "..."}
"""

import json
import os
import re
import sys
from pathlib import Path


def _project_browsers_root() -> Path:
    # scripts -> crawl -> server -> 项目根
    return Path(__file__).resolve().parents[3] / "playwright-browsers"


def find_chrome() -> str | None:
    env = os.environ.get("SMS_SCRAPLING_EXECUTABLE")
    if env and Path(env).exists():
        return env
    root = _project_browsers_root()
    # scrapling 自带的 playwright 期望 chromium-1217，优先用它
    preferred = root / "chromium-1217" / "chrome-win64" / "chrome.exe"
    if preferred.exists():
        return str(preferred)
    cands = sorted(root.glob("chromium-*/chrome-win64/chrome.exe"))
    return str(cands[0]) if cands else None


def extract_code(text: str):
    match = re.search(r"(?<!\d)(\d{4,8})(?!\d)", text or "")
    return match.group(1) if match else None


def main() -> None:
    if len(sys.argv) < 2:
        print(json.dumps({"status": "failed", "error": "missing code_url"}))
        return

    url = sys.argv[1]
    executable = (os.environ.get("SMS_SCRAPLING_EXECUTABLE") or "").strip() or None
    keyword = (os.environ.get("SMS_CODE_KEYWORD") or "").strip()

    if not executable:
        executable = find_chrome()

    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError as exc:
        print(json.dumps({"status": "failed", "error": f"scrapling not installed: {exc}"}, ensure_ascii=False))
        return

    kwargs_base = {
        "solve_cloudflare": True,
        "network_idle": True,
        "timeout": 180000,
        "wait": 3000,
    }
    if executable:
        kwargs_base["executable_path"] = executable

    page = None
    last_err = ""
    # Cloudflare 放行有波动：多轮重试，并交替无头/有头
    for attempt, headless in enumerate((True, False, True), start=1):
        try:
            candidate = StealthyFetcher.fetch(url, headless=headless, **kwargs_base)
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__}: {str(exc)[:200]}"
            print(f"[attempt {attempt}] fetch error: {last_err}", file=sys.stderr)
            continue
        try:
            row_count = len(candidate.css("table tr"))
        except Exception:  # noqa: BLE001
            row_count = 0
        if row_count >= 2:
            page = candidate
            break
        # 没有短信行，视为未放行，重试
        last_err = f"attempt {attempt}: rows={row_count}"
        print(f"[attempt {attempt}] no rows, retry", file=sys.stderr)

    if page is None:
        print(
            json.dumps(
                {"status": "pending", "note": f"接码页暂未就绪: {last_err}"},
                ensure_ascii=False,
            )
        )
        return

    # 逐行解析短信：td[0]=内容，td[1]=时间
    try:
        rows = page.css("table tr")
    except Exception:  # noqa: BLE001
        rows = []

    candidates = []  # (text, time)
    for r in rows:
        try:
            cells = [c.text.strip() for c in r.css("td")]
        except Exception:  # noqa: BLE001
            continue
        if not cells:
            continue
        text = cells[0]
        when = cells[1] if len(cells) > 1 else ""
        if not text:
            continue
        candidates.append((text, when))

    if not candidates:
        # 兜底：整页文本里找第一个验证码
        try:
            body = page.get_all_text() or ""
        except Exception:  # noqa: BLE001
            body = ""
        code = extract_code(body)
        if code:
            print(json.dumps({"status": "success", "code": code, "text": body[:300], "time": ""}, ensure_ascii=False))
        else:
            print(json.dumps({"status": "pending", "note": "未解析到短信行"}, ensure_ascii=False))
        return

    # 关键词过滤
    if keyword:
        kws = [k.strip().lower() for k in re.split(r"[|,，]", keyword) if k.strip()]
        matched = [(t, w) for (t, w) in candidates if any(k in t.lower() for k in kws)]
        if not matched:
            # 有短信但没有目标平台（如京东）的码：不能误用别人的验证码
            print(
                json.dumps(
                    {
                        "status": "pending",
                        "note": "暂无目标平台验证码",
                        "keyword": keyword,
                        "latest_text": candidates[0][0][:160],
                        "latest_time": candidates[0][1],
                    },
                    ensure_ascii=False,
                )
            )
            return
        pool = matched
    else:
        pool = candidates

    for text, when in pool:
        code = extract_code(text)
        if code:
            payload = {"status": "success", "code": code, "text": text[:300], "time": when}
            if keyword:
                payload["keyword"] = keyword
            print(json.dumps(payload, ensure_ascii=False))
            return

    # 有短信但都不是验证码
    latest_text, latest_time = pool[0]
    print(
        json.dumps(
            {
                "status": "pending",
                "note": "暂未匹配到验证码",
                "text": latest_text[:200],
                "time": latest_time,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
