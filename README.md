# 电商价格与库存监控平台（后端）

基于 **FastAPI + MySQL + Redis + Scrapy** 的多平台电商价格/库存监控后端服务。

支持淘宝/天猫、京东、拼多多、亚马逊、苏宁易购 5 大平台的商品监控、价格变更检测、告警、关键词采集与平台登录管理。

---

## 功能特点

### 商品与价格监控
- 商品 / SKU 全生命周期管理：新增、编辑、软删除、监控开关、批量采集与批量暂停
- Excel 模板下载与批量导入商品
- 价格快照采集（raw / hour / day 三级聚合），价格历史与字段变更记录
- 基于字段哈希的**变更检测引擎**（`change_detector` + `rule_engine`），自动分类变更类型并计算涨跌幅
- 商品分组与**跨平台同款比价**

### 告警与质量
- 告警规则 CRUD / 启停，告警记录单条与批量确认
- 告警聚合冲刷（`rule_engine.flush_aggregations`），按窗口合并推送
- 数据质量异常（`quality_issue`）自动识别、去重与人工复核
- 站内消息中心：告警 / 质量 / 死信 / 系统消息推送，未读数与已读管理

### 调度与可靠性
- 内置异步调度循环：抢 leader（Redis 分布式锁 + TTL）→ 注入到期采集任务 → 冲刷告警聚合
- 调度状态查看、手动 tick、暂停 / 恢复
- **死信队列**：连续采集失败达到阈值（默认 3 次）自动入队，支持重试 / 解决 / 丢弃
- 超时任务自动收尾，后台异常不导致进程退出

### 平台登录与接码
- 两种登录方式：
  1. **接码登录**：取号 → 平台触发短信 → 自动取码 → 提交登录
  2. **手动登录**：启动有头浏览器由用户自行登录，成功自动保存 Cookie
- 登录会话管理（创建 / 提交验证码 / 取消 / 查询），Cookie 状态检查
- 接码平台与接码订单管理（取号、取码、提交、取消），支持 scrapling 穿透 Cloudflare 抓码

### 关键词采集
- 关键词搜索任务：创建 → 启动对应 Spider → 拉取候选 → 确认入库

### 基础设施
- **JWT 认证**（access 720 分钟 / refresh 7 天）+ RBAC 权限（admin / operator / viewer）
- 操作审计中间件、请求链路追踪中间件、统一异常与统一响应封装
- 代理池管理：批量录入（多种格式）、连通性测试、全局唯一代理切换（写入 Redis 供采集端使用）
- 系统管理：用户、角色、权限点、字典、操作日志
- 仪表盘：概览统计与采集/告警趋势
- 采集端回写走 `/internal/*`（`X-Node-Api-Key` 鉴权）：快照、死信、搜索结果、登录态、接码结果
- 健康检查：`/api/health`、`/api/health/db`；交互式 API 文档 `/docs`

---

## 目录结构

```
.
├── server/                        # 后端（本文档重点）
│   ├── app/
│   │   ├── main.py                # 应用入口（FastAPI 工厂 + 调度循环）
│   │   ├── api/                   # 路由层
│   │   │   ├── auth.py            #   认证 /api/auth
│   │   │   ├── item.py            #   商品 /api/items、平台 /api/platforms
│   │   │   ├── item_group.py      #   商品分组 /api/item-groups
│   │   │   ├── search.py          #   关键词采集 /api/search-tasks
│   │   │   ├── alert.py           #   告警规则与记录 /api/alert-rules
│   │   │   ├── quality.py         #   质量异常 /api/quality-issues
│   │   │   ├── dead_letter.py     #   死信队列 /api/dead-letters
│   │   │   ├── scheduler.py       #   调度 /api/scheduler
│   │   │   ├── proxy.py           #   代理池 /api/proxies
│   │   │   ├── platform_login.py  #   登录会话 /api/platform-logins
│   │   │   ├── platform_auth.py   #   登录态/手动登录 /api/platform-auth
│   │   │   ├── sms.py             #   接码 /api/sms-providers、/api/sms-orders
│   │   │   ├── message.py         #   站内消息 /api/messages
│   │   │   ├── dashboard.py       #   仪表盘 /api/dashboard
│   │   │   ├── system.py          #   系统管理 /api/system
│   │   │   ├── internal.py        #   采集端回写 /internal/*
│   │   │   └── health.py          #   健康检查 /api/health
│   │   ├── service/               # 业务逻辑
│   │   │   ├── change_detector.py #   变更检测
│   │   │   ├── rule_engine.py     #   告警规则引擎与聚合
│   │   │   ├── quality_checker.py #   数据质量校验
│   │   │   ├── scheduler.py       #   调度服务（leader / 注入任务）
│   │   │   └── ...                #   其余模块业务逻辑
│   │   ├── dao/                   # 数据访问层
│   │   ├── schemas/               # Pydantic 请求/响应模型
│   │   ├── db/                    # SQLAlchemy 模型与会话
│   │   └── core/                  # 配置、鉴权、异常、审计、中间件、响应
│   ├── crawl/                     # Scrapy 采集工程（独立）
│   │   ├── crawl/
│   │   │   ├── spiders/           #   jd / taobao / pdd / amazon / suning / sms
│   │   │   ├── pipelines/         #   search / sms / snapshot 回写管道
│   │   │   ├── items.py           #   Item 定义
│   │   │   ├── proxy.py           #   读取 Redis 当前生效代理
│   │   │   └── settings.py        #   Scrapy + scrapy-redis 配置
│   │   ├── scripts/               # 各平台登录脚本、手动登录、scrapling 抓码
│   │   ├── cookies/  storage/     # 平台 Cookie 落盘
│   │   ├── requirements-crawl.txt
│   │   └── scrapy.cfg
│   ├── requirements.txt           # 后端依赖
│   ├── .env.example               # 环境变量模板
│   └── logs/                      # 运行日志（不入库）
│
├── frontend/                      # Vue3 + Element Plus 前端（另见前端文档）
├── sql/
│   └── ecom_monitor.sql           # 建库建表 + 种子数据（单文件）
├── 模块功能说明文档.md              # 详细模块说明
└── README.md
```

> 采集端与后端通过 HTTP 交互：Scrapy Pipeline 将结果回写到 `/internal/*`，后端调度器向 Redis 队列注入采集请求（`ecom:sc:{site_group}:requests`）。

---

## 快速开始（后端 server）

### 环境要求

| 依赖 | 版本建议 |
|---|---|
| Python | 3.11+ |
| MySQL | 8.x |
| Redis | 6.x+ |
| Scrapy（采集端） | 2.19 + scrapy-redis + scrapy-playwright |

### 1. 初始化数据库

执行单文件建库脚本（含建库、26 张表、种子数据）：

```bash
mysql -uroot -p < sql/ecom_monitor.sql
```

### 2. 安装后端依赖

```bash
cd server
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
cp .env.example .env
```

按需修改 `.env`（默认值即可本地跑通）：

```env
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=ecom
MYSQL_PASSWORD=ecom123
MYSQL_DB=ecom_monitor

REDIS_URL=redis://127.0.0.1:6379/0

SECRET_KEY=change-me-in-prod      # 生产环境务必更换
NODE_API_KEY=dev-node-api-key     # 采集端回写接口密钥
SCHEDULER_TICK_SEC=10             # 调度周期
DEAD_THRESHOLD=3                  # 死信阈值
```

### 4. 启动后端

```bash
uvicorn app.main:app --reload --port 8000
```

- API 文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/api/health
- 数据库检查：http://127.0.0.1:8000/api/health/db
- 默认管理员：**admin / admin123**（首次登录请修改）

> 应用启动时会自动拉起调度循环（`SCHEDULER_ENABLED=true` 时），无需额外进程。

### 5.（可选）启动采集端

```bash
cd crawl
pip install -r requirements-crawl.txt
playwright install chromium

# 示例：启动京东详情采集
scrapy crawl jd_detail -a site_group=jd

# 关键词搜索 Spider 需要 task_id / keyword 等参数，
# 由后端「关键词采集」页触发（POST /api/search-tasks/{task_id}/run），无需手动启动：
#   scrapy crawl jd_search -a site_group=cn-main -a task_id=... -a keyword=... -a platform_id=... -a limit=20
```

平台 Cookie 就绪后即可采集：

```bash
# 有头浏览器手动登录（登录成功自动保存 Cookie 并关窗）
python scripts/manual_login.py jd
```

---

## 主要接口速览

| 模块 | 前缀 | 说明 |
|---|---|---|
| 认证 | `/api/auth` | 登录、刷新、当前用户、改密 |
| 商品 | `/api/items` | 商品 CRUD、导入、立即采集、价格历史 |
| 平台 | `/api/platforms` | 平台字典与适配配置 |
| 分组 | `/api/item-groups` | 分组与跨平台比价 |
| 搜索 | `/api/search-tasks` | 关键词采集任务 |
| 告警 | `/api/alert-rules` | 规则与告警记录 |
| 质量 | `/api/quality-issues` | 质量异常复核 |
| 死信 | `/api/dead-letters` | 失败任务重试 |
| 调度 | `/api/scheduler` | 状态、tick、暂停 |
| 代理 | `/api/proxies` | 代理池管理与切换 |
| 登录 | `/api/platform-logins`、`/api/platform-auth` | 接码登录、手动登录 |
| 接码 | `/api/sms-providers`、`/api/sms-orders` | 取号、取码 |
| 消息 | `/api/messages` | 站内消息 |
| 系统 | `/api/system` | 用户、角色、字典、审计日志 |
| 仪表盘 | `/api/dashboard` | 概览与趋势 |
| 内部 | `/internal/*` | 采集端回写（`X-Node-Api-Key`） |

---

## 技术栈

**后端**：FastAPI · Uvicorn · SQLAlchemy 2 · PyMySQL · Pydantic v2 · PyJWT · argon2-cffi · Redis · httpx · openpyxl · scrapling

**采集端**：Scrapy · scrapy-redis · scrapy-playwright · playwright-stealth

**数据**：MySQL 8（26 张表）· Redis（任务队列 / 分布式锁 / 代理状态）
