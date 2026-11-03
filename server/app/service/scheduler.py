import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from redis import Redis as RedisPy
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.dao import scheduler as scheduler_dao
from app.db.models import CrawlTaskLog, MonitorItem, Platform


settings = get_settings()


# ==================== 双层调度：业务调度（Manager） ====================


class SchedulerService:
    """Manager 业务调度：扫描到期商品 -> 构造种子 -> LPUSH scrapy-redis 队列。

    职责：
      1. 每 SCHEDULER_TICK_SEC 扫一次 monitor_status=1 且 next_run_time<=NOW() 的商品
      2. 按 site_group 分组，构造种子 Request 并写入 Redis 队列
      3. 行级原子推进 next_run_time，防重复调度
      4. 批次记录写 crawl_task_log，结束后归集 success/fail/dead
      5. leader 主备抢锁（Redis SETNX），备实例只待命
    """

    def __init__(self):
        self.settings = get_settings()
        self._redis: Optional[RedisPy] = None
        self._leader_token = (
            f"{self.settings.app_env}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        )

    def _get_redis(self) -> RedisPy:
        if self._redis is None:
            self._redis = RedisPy.from_url(self.settings.redis_url_compat)
        return self._redis

    # ---------- 详情采集 Worker 自动拉起 ----------

    # site_group(平台编码) -> 详情 Spider 名称
    DETAIL_SPIDERS = {
        "jd": "jd_detail",
        "taobao": "taobao_detail",
        "suning": "suning_detail",
        "amazon": "amazon_detail",
        "pdd": "pdd_detail",
    }

    @staticmethod
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

    @staticmethod
    def _kill_pid(pid: int) -> None:
        if not pid:
            return
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F", "/T"],
                    capture_output=True,
                    timeout=8,
                )
            else:
                os.kill(pid, 9)
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _cookie_mtime(site_group: str) -> int:
        """返回该平台登录态文件的最新修改时间（秒），无则 0。"""
        server_dir = Path(__file__).resolve().parents[2]
        newest = 0
        for base in (server_dir / "crawl" / "storage", server_dir / "crawl" / "cookies"):
            for name in (f"{site_group}.json", f"{site_group}_state.json"):
                path = base / name
                if path.exists():
                    try:
                        newest = max(newest, int(path.stat().st_mtime))
                    except OSError:
                        pass
        return newest

    def ensure_detail_worker(self, site_group: str) -> None:
        """确保某 site_group 的详情 Spider 在运行（按分组单实例）。

        若登录态文件比 Worker 启动时间更新，则杀掉旧 Worker 并用新 Cookie 重启，
        避免登录后仍沿用登录前的浏览器上下文。
        """
        spider = self.DETAIL_SPIDERS.get(site_group)
        if not spider:
            return
        r = self._get_redis()
        lock_key = f"sc:worker:{site_group}"
        ts_key = f"sc:worker:{site_group}:ts"
        current = r.get(lock_key)
        if current:
            pid = None
            try:
                pid = int(current)
            except (TypeError, ValueError):
                pid = None
            if pid and self._pid_alive(pid):
                ts_raw = r.get(ts_key)
                try:
                    worker_ts = int(ts_raw) if ts_raw else 0
                except (TypeError, ValueError):
                    worker_ts = 0
                proxy_ts_raw = r.get("proxy:active:ts")
                try:
                    proxy_ts = int(proxy_ts_raw) if proxy_ts_raw else 0
                except (TypeError, ValueError):
                    proxy_ts = 0
                cookie_mtime = self._cookie_mtime(site_group)
                if (cookie_mtime and cookie_mtime > worker_ts) or (
                    proxy_ts and proxy_ts > worker_ts
                ):
                    # 登录态或启用代理更新了，重启 Worker 以重新加载
                    self._kill_pid(pid)
                    r.delete(lock_key)
                    r.delete(ts_key)
                else:
                    return
            else:
                r.delete(lock_key)
                r.delete(ts_key)

        crawl_dir = Path(__file__).resolve().parents[2] / "crawl"
        log_dir = Path(__file__).resolve().parents[2] / "logs" / "detail"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{site_group}.log"

        cmd = [
            sys.executable,
            "-m",
            "scrapy",
            "crawl",
            spider,
            "-a",
            f"site_group={site_group}",
            "-s",
            "CLOSESPIDER_TIMEOUT=300",
        ]
        env = os.environ.copy()
        env["INTERNAL_API_BASE"] = os.environ.get(
            "INTERNAL_API_BASE", "http://127.0.0.1:8000"
        )
        env["NODE_API_KEY"] = self.settings.node_api_key
        env["PYTHONIOENCODING"] = "utf-8"

        flags = 0x00000200 | 0x08000000 if os.name == "nt" else 0
        try:
            with open(log_path, "ab") as log_file:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(crawl_dir),
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    env=env,
                    creationflags=flags,
                )
        except Exception:  # noqa: BLE001 启动失败不阻塞入队
            return
        r.set(lock_key, str(proc.pid), ex=300)
        r.set(ts_key, str(int(time.time())), ex=300)

    # ---------- leader 锁（主备） ----------

    def try_acquire_leader(self) -> bool:
        """抢锁；若锁已经是本进程持有则续期。"""
        r = self._get_redis()
        acquired = bool(
            r.set(
                "scheduler:leader",
                self._leader_token,
                nx=True,
                ex=self.settings.scheduler_leader_ttl,
            )
        )
        if acquired:
            return True
        if r.get("scheduler:leader") == self._leader_token.encode():
            self.refresh_leader()
            return True
        return False

    def refresh_leader(self) -> None:
        r = self._get_redis()
        if r.get("scheduler:leader") == self._leader_token.encode():
            r.expire("scheduler:leader", self.settings.scheduler_leader_ttl)

    def is_leader(self) -> bool:
        r = self._get_redis()
        return r.get("scheduler:leader") == self._leader_token.encode()
    # ---------- 全局暂停开关 ----------

    def is_paused(self) -> bool:
        return bool(self._get_redis().get("scheduler:paused"))

    def set_paused(self, paused: bool) -> bool:
        r = self._get_redis()
        if paused:
            r.set("scheduler:paused", "1")
        else:
            r.delete("scheduler:paused")
        return paused

    # ---------- 队列积压 ----------

    def queue_lag(self) -> dict:
        r = self._get_redis()
        lag = {}
        for key in r.keys("ecom:sc:*:requests"):
            text = key.decode() if isinstance(key, bytes) else key
            parts = text.split(":")
            group = parts[2] if len(parts) > 2 else text
            lag[group] = r.llen(key)
        return lag

    # ---------- 站点暂停开关 ----------

    def is_site_paused(self, site_group: str) -> bool:
        r = self._get_redis()
        return bool(r.get(f"site:{site_group}:pause"))

    # ---------- 单轮调度 ----------

    def finalize_stale_tasks(self, db: Session, older_than_min: int = 15) -> int:
        """把长时间停在 running 的任务标记为失败（无采集节点/被反爬拦截等）。"""
        cutoff = datetime.now() - timedelta(minutes=older_than_min)
        rows = (
            db.query(CrawlTaskLog)
            .filter(
                CrawlTaskLog.status == "running",
                CrawlTaskLog.start_time < cutoff,
            )
            .all()
        )
        for row in rows:
            row.status = "failed"
            row.end_time = datetime.now()
            try:
                row.cost_ms = int(
                    (row.end_time - row.start_time).total_seconds() * 1000
                )
            except Exception:  # noqa: BLE001
                pass
            if not row.error_summary:
                row.error_summary = "采集任务超时未回传结果（无节点消费或被反爬拦截）"
            db.add(row)
        if rows:
            db.commit()
        return len(rows)

    def schedule_once(self, db: Session, batch_size: int = 500) -> dict:
        """执行一次调度注入。返回本次统计。"""
        if not self.is_leader():
            return {"status": "standby", "injected": 0}

        # 清理长时间停在 running 的任务，避免前端永远显示"进行中"
        try:
            self.finalize_stale_tasks(db)
        except Exception:  # noqa: BLE001
            pass

        seeds = scheduler_dao.build_seed_requests(db, batch_size=batch_size)
        if not seeds:
            return {"status": "ok", "injected": 0}

        groups: dict[str, list] = {}
        for seed in seeds:
            site_group = seed.get("site_group") or "cn-main"
            groups.setdefault(site_group, []).append(seed)

        r = self._get_redis()
        injected = 0
        task_ids: List[str] = []

        now = int(time.time() * 1000)
        for site_group, group_seeds in groups.items():
            if self.is_site_paused(site_group):
                continue
            task_id = f"sched_{now}_{site_group}"
            pipe = r.pipeline()
            key = f"ecom:sc:{site_group}:requests"
            for seed in group_seeds:
                seed["task_id"] = task_id
                pipe.lpush(key, json.dumps(seed, ensure_ascii=False))
            pipe.execute()
            injected += len(group_seeds)
            task_ids.append(task_id)
            # 确保该分组的详情 Spider 在消费
            self.ensure_detail_worker(site_group)
            scheduler_dao.create_crawl_task_log(
                db,
                task_id=task_id,
                trigger_type="schedule",
                total_count=len(group_seeds),
            )

        # 行级原子推进 next_run_time，防重复调度（注意用数据库主键 db_id）
        for seed in seeds:
            self.advance_next_run_time(
                db, seed.get("db_id"), seed.get("freq_group")
            )
        db.commit()

        return {"status": "ok", "injected": injected, "task_ids": task_ids[:5]}

    # ---------- 批次归集 ----------

    def finalize_task(
        self,
        db: Session,
        task_id: str,
        success_count: int,
        fail_count: int,
        dead_count: int,
        strategy_stat: Optional[dict] = None,
    ) -> None:
        scheduler_dao.update_task_log(
            db,
            task_id=task_id,
            success_count=success_count,
            fail_count=fail_count,
            dead_count=dead_count,
            strategy_stat=strategy_stat,
            status="success" if dead_count == 0 and fail_count == 0 else "partial",
        )
        db.commit()

    # ---------- 下次运行时间推进 ----------

    def advance_next_run_time(self, db: Session, item_id: int, freq: str) -> None:
        item = (
            db.query(MonitorItem)
            .filter(MonitorItem.id == item_id, MonitorItem.is_deleted == 0)
            .first()
        )
        if not item:
            return
        interval = self._freq_seconds(freq)
        item.next_run_time = datetime.fromtimestamp(time.time() + interval)
        db.add(item)

    @staticmethod
    def _freq_seconds(freq: str) -> int:
        mapping = {"5m": 300, "30m": 1800, "1h": 3600, "daily": 86400}
        if freq and freq.startswith("cron:"):
            return 300
        return mapping.get(freq, 1800)

    # ---------- 手动/重试投递 ----------

    def enqueue_items(
        self, db: Session, items: List[MonitorItem], trigger_type: str = "manual"
    ) -> dict:
        """把指定商品按 site_group 投递到 scrapy-redis 队列。"""
        if not items:
            return {"injected": 0, "task_ids": []}

        now_ms = int(time.time() * 1000)
        groups: dict[str, list] = {}
        for item in items:
            platform = db.query(Platform).filter(Platform.id == item.platform_id).first()
            adapter = (platform.adapter_config if platform else None) or {}
            site_group = adapter.get("site_group") or "cn-main"
            groups.setdefault(site_group, []).append(item)

        r = self._get_redis()
        injected = 0
        task_ids: List[str] = []
        for site_group, group_items in groups.items():
            task_id = f"{trigger_type}_{now_ms}_{site_group}"
            key = f"ecom:sc:{site_group}:requests"
            pipe = r.pipeline()
            for item in group_items:
                seed = scheduler_dao.build_seed_request(item, site_group)
                seed["task_id"] = task_id
                seed["retry_type"] = trigger_type
                pipe.lpush(key, json.dumps(seed, ensure_ascii=False))
            pipe.execute()
            injected += len(group_items)
            task_ids.append(task_id)
            # 确保该分组的详情 Spider 在消费
            self.ensure_detail_worker(site_group)
            scheduler_dao.create_crawl_task_log(
                db,
                task_id=task_id,
                trigger_type=trigger_type,
                total_count=len(group_items),
            )
        # 手动触发也推进下次运行时间，避免调度器此刻重复补采
        for item in items:
            self.advance_next_run_time(db, item.id, item.crawl_freq)
        db.commit()
        return {"injected": injected, "task_ids": task_ids}


# 全局单例
scheduler_service = SchedulerService()
