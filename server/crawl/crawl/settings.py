# Scrapy settings for crawl project (Scrapy-Redis distributed preset)
#
# 架构约定（设计报告 §5.2）：
#   Manager 种子入队 → scrapy-redis 队列 → Spider BRPOP 消费
#   频率语义在 Manager 层（next_run_time）；Scrapy 层只负责尽快消费完队列。

import os

BOT_NAME = "crawl"

SPIDER_MODULES = ["crawl.spiders"]
NEWSPIDER_MODULE = "crawl.spiders"

ADDONS = {}

# ==================== Scrapy-Redis 分布式 ====================
# Redis 连接（可用环境变量 REDIS_URL 覆盖，部署时指向 Redis 集群/哨兵）
# ?protocol=2 强制 RESP2：redis-py>=6 默认发 HELLO 握手(需要 Redis>=6)，
# 本地学习用 Redis 3.0(Windows 旧移植版) 不认识 HELLO 会报 "unknown command 'HELLO'"。
# 升级到 Redis 7 后此参数可留可删（RESP2 一直兼容）。
REDIS_URL = os.environ.get(
    "REDIS_URL", "redis://localhost:6379/0?protocol=2"
)

# 调度器与去重改用 Redis 实现：多进程/多节点共享请求队列与去重集合
SCHEDULER = "scrapy_redis.scheduler.Scheduler"
DUPEFILTER_CLASS = "scrapy_redis.dupefilter.RFPDupeFilter"

# 队列持久化：进程退出后不清空 Redis 队列，重启/扩容后继续消费（at-least-once）
SCHEDULER_PERSIST = True

# 调度内部队列/去重键（注意：scrapy-redis 只支持 %(spider)s 占位符——
# 源码 scheduler.py:140 与 dupefilter.py:132 用 {"spider": spider.name} 格式化，
# 填其他占位符会 KeyError）。
# 种子队列（Spider 消费入口）不在此配置，由 BaseRedisSpider.__init__ 按
# site_group 动态设置 redis_key = ecom:sc:{site_group}:requests。
# 内部调度队列用 :scheduled 后缀与种子队列分开，避免 pickle(调度队列)与
# 种子数据混装在同一 key。
SCHEDULER_QUEUE_KEY = "ecom:sc:%(spider)s:scheduled"
SCHEDULER_DUPEFILTER_KEY = "ecom:sc:%(spider)s:dupefilter"

# TODO(接 Manager 前)：内部调度队列目前按 spider 名隔离，尚未按 site_group
# 隔离——跨组同名 spider 会共享内部队列。彻底隔离需自定义 Scheduler 子类
# 在 open() 中用 spider.site_group 格式化键。

# 统计汇聚（scrapy-redis 0.9+，可选开启；多节点 stats 汇总到 Redis）
# REDIS_STATS_CLASS = "scrapy_redis.stats.RedisStatsCollector"

# ==================== 基础爬取策略 ====================
# 电商采集目标站点 robots 约束由业务侧（站点档案/合规开关）管理，不走 robots.txt
ROBOTSTXT_OBEY = False

CONCURRENT_REQUESTS = 16
CONCURRENT_REQUESTS_PER_DOMAIN = 1
DOWNLOAD_DELAY = 1

# 详情页请求由 Manager 投递、携带业务唯一键，关闭去重由种子 meta 的 dont_filter 控制
# （scrapy-redis 层仍保留 dupefilter 供列表页/meta 页按需启用）

COOKIES_ENABLED = False
TELNETCONSOLE_ENABLED = False

DEFAULT_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# 浏览器 UA：scrapy-playwright 会把 Scrapy 请求头套到浏览器请求上，
# 若沿用默认 "Scrapy/x.y" 会被风控识别（目标站点可能直接返回 JS 探针页）
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# ==================== 中间件（后续任务接入，先占位） ====================
# DOWNLOADER_MIDDLEWARES = {
#     "crawl.middlewares.fingerprint.FingerprintMiddleware": 300,
#     "crawl.middlewares.proxy_rotator.ProxyRotatorMiddleware": 350,
#     "crawl.middlewares.strategy_select.StrategySelectMiddleware": 400,
#     "crawl.middlewares.api_rewrite.ApiRewriteMiddleware": 450,
#     "crawl.middlewares.playwright_render.PlaywrightMiddleware": 500,
#     "crawl.middlewares.budget_retry.BudgetRetryMiddleware": 550,
#     "crawl.middlewares.seed_meta.SeedMetaMiddleware": 580,
# }

# ==================== Pipeline ====================
ITEM_PIPELINES = {
    # 搜索结果回写（SearchBatch）
    "crawl.pipelines.search.SearchResultPipeline": 150,
    # 接码结果回写（SmsResult）
    "crawl.pipelines.sms.SmsResultPipeline": 160,
    # 采集快照回写（CrawlItem）
    "crawl.pipelines.snapshot.SnapshotPipeline": 500,
}

# ==================== 限速与自动降频 ====================
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1
AUTOTHROTTLE_MAX_DELAY = 60
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0
AUTOTHROTTLE_DEBUG = False

# ==================== 重试（分级重试由 BudgetRetryMiddleware 接管） ====================
RETRY_ENABLED = True
RETRY_TIMES = 2
RETRY_HTTP_CODES = [408, 429, 500, 502, 503, 504, 522, 524]

DOWNLOAD_TIMEOUT = 30

# ==================== scrapy-playwright 浏览器渲染（browser 策略档） ====================
# 浏览器内核目录（项目内自包含，可环境变量覆盖）
os.environ.setdefault(
    "PLAYWRIGHT_BROWSERS_PATH",
    r"/程序/电商数据监控平台\playwright-browsers",
)

# Scrapy 2.13+ 默认 asyncio reactor，此处显式声明与 scrapy-playwright 对齐
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

# 全局安装 Playwright 下载器：meta['playwright']=True 的请求走浏览器渲染，
# 其余请求自动回落普通 HTTP 下载（不影响现有 api/page 策略）
DOWNLOAD_HANDLERS = {
    "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
}

# 每进程渲染并发上限（设计报告 §5.2.4：限制渲染槽）
PLAYWRIGHT_MAX_PAGES = 4

# 浏览器启动参数：关闭自动化标志 + 常规无害参数，降低被识别概率
PLAYWRIGHT_LAUNCH_OPTIONS = {
    "args": [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--no-first-run",
        "--no-default-browser-check",
    ],
}

INTERNAL_API_BASE = os.environ.get("INTERNAL_API_BASE", "http://127.0.0.1:8000")
NODE_API_KEY = os.environ.get("NODE_API_KEY", "dev-node-api-key")
# 登录 Cookie 目录（每个平台一个 <code>.json）
SEARCH_COOKIES_DIR = os.environ.get("SEARCH_COOKIES_DIR", os.path.join(os.path.dirname(__file__), "..", "cookies"))
# 登录态 storage_state 目录（Playwright storage_state，登录器导出）
SEARCH_STORAGE_DIR = os.environ.get("SEARCH_STORAGE_DIR", os.path.join(os.path.dirname(__file__), "..", "storage"))

# ==================== 日志与导出 ====================
LOG_LEVEL = os.environ.get("SCRAPY_LOG_LEVEL", "INFO")
FEED_EXPORT_ENCODING = "utf-8"

# 请求指纹缓存目录（本地辅助，主去重在 Redis）
# HTTPCACHE_ENABLED 保持关闭，避免与 Redis 去重/预算重试冲突
HTTPCACHE_ENABLED = False
