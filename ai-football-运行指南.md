# ai-football 运行指南

> 项目位置：`G:\polymarket\Sports\ai-football`（后端单体，**没有前端**；演示站是作者另部署的 [www.ai7zym.online）](http://www.ai7zym.online）)

---

## 一、先说结论

| 问题                            | 结论                                                                               |
| ----------------------------- | -------------------------------------------------------------------------------- |
| 能用 README 的「方式一：导入 SQL 快速启动」吗 | ❌ **不行**。作者明确说明数据库导出文件体积过大、未上传仓库（README 第 29 行）。仓库里没有 `.sql` 文件                  |
| 能用 README 的「方式二：从空数据库初始化」吗    | ✅ 可以，但**必须包含本次新增的迁移** `d4e8b1c6f205`，否则启动必崩（详见第七节）                               |
| 需要哪些外部账号                      | **API-Football**（必需，免费层 100 次/天）、**DeepSeek**（LLM 分析，可选但强烈建议）                    |
| 模型文件齐全吗                       | ✅ 齐全。`prediction/models/` 有 **300 个模型 `.pkl`** + `feature_cols.pkl`（78 维特征），开箱即用 |

---

## 二、前置条件

| 项      | 要求          | 说明                                                       |
| ------ | ----------- | -------------------------------------------------------- |
| Python | **3.12+**   | `requirements.txt` 里 pandas 3.0.3 / numpy 2.4.6 等需要较新解释器 |
| MySQL  | **8.0+**    | 唯一支持的数据库（迁移里大量使用 `mysql.*` 专有类型）                         |
| 磁盘     | **≥ 10 GB** | 依赖里有 torch / transformers / xgboost，装完数 GB               |
| 内存     | 建议 8 GB     | 只做推理 4 GB 够；重新训练建议更高                                     |

---

## 三、启动步骤

### 1) 建虚拟环境并装依赖

```bash
cd G:\polymarket\Sports\ai-football\backend

python -m venv .venv
.venv\Scripts\activate            # PowerShell: .\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

> 依赖包很大，建议加国内镜像加速：  
> `pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/`

### 2) 创建数据库

```sql
CREATE DATABASE football CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 3) 生成配置文件

```bash
copy .env.example .env            # PowerShell: Copy-Item .env.example .env
```

然后编辑 `backend\.env`，**这几项必须填**：

| 变量                                                            | 是否必填     | 说明                                                                  |
| ------------------------------------------------------------- | -------- | ------------------------------------------------------------------- |
| `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` | ✅        | 按你的 MySQL 实例填                                                       |
| `API_FOOTBALL_KEY`                                            | ✅        | 不填则所有同步任务直接跳过，**拿不到任何数据**                                           |
| `API_FOOTBALL_BASE_URL`                                       | ✅ **易漏** | `.env.example` 里默认是**空值**，必须自己填：`https://v3.football.api-sports.io` |
| `DEEPSEEK_API_KEY`                                            | 建议       | 不填则预测里的 LLM 深度分析为空                                                  |
| `FOOTBALL_DATA_BASE_URL`                                      | ❌        | 保留默认值                                                               |
| `UNDERSTAT_BASE_URL`                                          | ❌        | 保留默认值                                                               |

### 4) 建表

```bash
alembic upgrade head
```

应看到 `Running upgrade ... -> d4e8b1c6f205`。迁移链共 **26 个 revision、单头**。

> ⚠️ **这一步是本次修复的关键**。修复前的迁移链会建出一张缺 `start_hour` 列的  
> `scheduler_tasks`，导致下一步启动直接崩溃。详见第七节。

### 5) 启动服务

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

验证：

```bash
curl http://127.0.0.1:8000/api/health        # {"status":"ok"}
```

交互式文档：[http://127.0.0.1:8000+/docs](http://127.0.0.1:8000/docs)

> 启动时会自动注册并运行 **11 个定时任务**（`scheduler.py: init_scheduler()`）。  
> 此时数据库是空的，定时任务只会空转，不影响启动。

### 6) 灌数据（顺序很重要）

**第一步：从 API-Football 拉基础元数据**（联赛 + 球队）。这一步会按白名单自动  
把 39/140/78/135/61 等联赛置为 `enabled`：

```bash
curl -X POST http://127.0.0.1:8000/api/scheduler/leagues/sync
curl -X POST http://127.0.0.1:8000/api/scheduler/teams/sync
```

**第二步：用免费源批量回填历史**（无 key、无次数限制，想拉多少拉多少）：

```bash
python tools/sync_football_data.py --seasons 2023 2024 2025   # 比分/半场/射门/射正/角球/犯规
python tools/sync_understat.py     --seasons 2023 2024 2025   # 真实 xG
```

**第三步：用 API-Football 补它独有的东西**（注意 100 次/天配额）：

```bash
curl -X POST http://127.0.0.1:8000/api/scheduler/standings/sync   # 积分榜（D 组 12 个特征必需）
curl -X POST http://127.0.0.1:8000/api/scheduler/fixtures/sync    # 近 7 天赛程
```

> 为什么不直接全用 API-Football？因为免费层只有 **100 次/天**，而回填一个赛季  
> 光统计就要几百次调用。免费源承担了 78 个特征里的大部分原料。

**第四步（可选）：伤停数据**

```bash
python tools/sync_injuries.py --date 2026-10-07
python tools/sync_injuries.py --fixtures 1234567
```

### 7) 跑预测

```bash
python tools/manual_predict.py       # 交互式，选一场比赛预测
python tools/batch_predict.py        # 批量预测
```

或者走 API：

```bash
curl -X POST http://127.0.0.1:8000/api/predict/123456
curl "http://127.0.0.1:8000/api/predictions?date=2026-10-07&page=1&page_size=20"
```

### 8)（可选）重新生成特征并重训模型

```bash
python prediction/features.py        # 从 DB 重新生成 features.csv
python prediction/train.py           # 重新训练
```

> 仓库自带的 `features.csv`（65,310 行）与 301 个模型是基于**作者的原始数据库**训练出来的。  
> 你灌入的数据集不同，如果要让模型匹配自己的数据，必须重跑这两步。

---

## 四、常用接口速查

| 方法   | 路径                                                                          | 用途       |
| ---- | --------------------------------------------------------------------------- | -------- |
| GET  | `/api/health`                                                               | 健康检查     |
| GET  | `/api/leagues` `/api/teams` `/api/players` `/api/standings` `/api/fixtures` | 分页查询     |
| GET  | `/api/fixtures/{id}`                                                        | 单场详情     |
| POST | `/api/predict/{fixture_id}`                                                 | 单场预测     |
| GET  | `/api/predictions`                                                          | 查询预测结果   |
| GET  | `/api/scheduler/status`                                                     | 定时任务状态   |
| POST | `/api/scheduler/{task_id}/trigger`                                          | 手动触发任意任务 |
| POST | `/api/scheduler/{task_id}/start` `/stop`                                    | 启停任务     |
| GET  | `/api/scheduler/logs`                                                       | 任务执行日志   |

---

## 五、定时任务（默认全部启用）

| 任务 id                    | 名称                     | 调度       |
| ------------------------ | ---------------------- | -------- |
| `league_sync`            | 联赛同步                   | 每天 02:00 |
| `team_sync`              | 球队同步                   | 每天 02:30 |
| `player_sync`            | 球员同步                   | 每天 03:00 |
| `standing_sync`          | 积分榜同步                  | 每天 04:00 |
| `fixture_daily`          | 赛程同步                   | 每天 05:00 |
| `football_data_backfill` | football-data.co.uk 回填 | 每天 05:30 |
| `understat_sync`         | Understat xG 回填        | 每天 06:00 |
| `injury_sync`            | 伤停同步                   | 每天 11:30 |
| `auto_predict`           | 赛前自动预测                 | 每天 12:00 |
| `fixture_live`           | 实时赛况                   | 每 2 分钟   |
| `backfill_pred`          | 预测结果回填                 | 每 1 小时   |

配置存在 `scheduler_tasks` 表，可直接改，也可用 `/api/scheduler/{id}/start|stop` 启停。

---

## 六、本次修复：一个会导致「装完起不来」的迁移缺陷

### 症状

按 README「方式二」走完 `alembic upgrade head` 后启动服务，进程直接退出：

```
MySQL 1054: Unknown column 'start_hour' in 'field list'
```

### 原因

- `scheduler_tasks` 由迁移 `f1173d35c3c1` 创建，**漏了 `start_hour` 列**；
- 整条链上**没有任何 `upgrade()` 补过它**（`aa8539407817` 里出现过一次，  
  但那是在它的 `downgrade()` 里，方向相反）；
- 而 `app/services/scheduler.py` 的 `_seed_defaults()` 会显式插入这一列：
  ```sql
  INSERT IGNORE INTO scheduler_tasks
      (id, name, interval_seconds, start_hour, is_enabled) VALUES (...)
  ```
- `init_scheduler()` 在 FastAPI 的 `lifespan` 里被调用，异常直接导致**应用起不来**。  
  注意 `INSERT IGNORE` **不会**吞掉「列不存在」这类名称解析错误。

> 作者自己的库应该是从 SQL dump 导入的（schema 正确），所以这条迁移路径  
> 从未被真正跑通过——只有从空库初始化的人会踩到。

### 修复

新增迁移 **`d4e8b1c6f205_add_scheduler_start_hour.py`**（`down_revision = c1f4a7b2d903`）：

1. 补 `scheduler_tasks.start_hour`（`DOUBLE`，支持 5.5 = 05:30 这种小数）；
2. 把 `interval_seconds` 从 `NOT NULL` 放宽为可空 —— 因为 `auto_predict` 这类  
   纯定时任务本来就不设间隔，代码会插入 `None`；
3. **幂等**：先用 `sa.inspect()` 探测列是否存在再改，所以从作者 SQL dump 导入的、  
   已经带有该列的库重复执行也不会报错。

验证：SQLite 复现「迁移前插入失败 / 迁移后 11 个任务全部插入成功」，  
14 项断言全通过（脚本见 `_verify/test_scheduler_migration.py`）。

---

## 七、常见问题

**Q：`pip install` 卡住 / 超时？**  
换国内镜像：`-i https://mirrors.aliyun.com/pypi/simple/`。  
（清华源 `pypi.tuna.tsinghua.edu.cn` 已失效，会超时。）

**Q：同步任务跑了但数据库没数据？**  
按顺序检查：① `API_FOOTBALL_BASE_URL` 是否为空（`.env.example` 默认就是空的）；  
② `API_FOOTBALL_KEY` 是否有效；③ 联赛是否 `enabled`（白名单在  
`app/core/whitelist.py`，只同步 `enabled=True` 的联赛）。

**Q：想加苏超（league_id 179）？**  
它**不在白名单**里，需手动置位：

```sql
UPDATE leagues SET enabled = 1 WHERE id = 179;
```

另外注意：Understat **不覆盖苏超**，该联赛的 xG 只能靠 API-Football。

**Q：预测返回 400 / 特征缺失？**  
说明该场比赛所需的三个来源没数据。检查 `fixtures`、`fixture_statistics`、  
`standings` 三张表是否都有对应记录——特征工程只读这三张表。

**Q：能直接用 SQLite 跑吗？**  
不能。迁移大量使用 `mysql.*` 专有类型，且 `scheduler.py` 用了 `INSERT IGNORE`  
等 MySQL 语法。

---

## 八、目录速查

```text
backend/
├── main.py                     # FastAPI 入口（uvicorn main:app）
├── .env.example                # 环境变量模板
├── requirements.txt
├── alembic/versions/           # 26 个迁移，单头 d4e8b1c6f205
├── app/
│   ├── api/                    # REST 路由
│   ├── core/                   # config / whitelist / log_config
│   ├── models/                 # ORM（injuries 是本次新增）
│   ├── services/
│   │   ├── fixture_matching.py       # ★ 共享：队名解析 + 合成 fixture ID
│   │   ├── football_data_service.py  # ★ 免费历史回填
│   │   ├── understat_service.py      # ★ 免费真实 xG
│   │   ├── injury_service.py         # ★ 伤停
│   │   └── scheduler.py              # 定时任务
│   └── data/team_aliases.json  # 148 条队名别名
├── prediction/
│   ├── models/                 # 300 个模型 pkl + feature_cols.pkl
│   ├── features.py             # 特征工程（只读 fixtures / fixture_statistics / standings）
│   ├── predict.py              # 单场预测
│   └── train.py
├── tools/                      # CLI 工具
└── docs/DATA_SOURCES.md        # 数据源详解
```
