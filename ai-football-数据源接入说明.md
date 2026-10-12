# ai-football 数据源接入完成说明

> 项目落盘位置：`G:\polymarket\Sports\ai-football`（本地，298 MB / 399 文件 / 301 个模型 pkl）
> 本次接入：**football-data.co.uk**（免费历史回填）、**API-Football `/injuries`**（伤停）、**Understat**（真实 xG）

---

## 一、结论速览

| 数据源 | 需要 key | 覆盖联赛 | 提供内容 | 新增文件 |
|---|---|---|---|---|
| **football-data.co.uk** | **否** | 英/苏/五大联赛 | 比分、半场比分、射门、射正、角球、犯规、赔率 | `football_data_service.py` |
| **Understat** | **否** | 五大联赛 | **真实 xG** | `understat_service.py` |
| **API-Football `/injuries`** | 是 | 全部已启用联赛 | 伤停 | `injury_service.py` + `injury.py` |

**核心价值**：AI-football 的 78 维特征里，`h_xg5` / `a_xg5` / `xg_diff5` **3 个特征来自真实 xG**。
原项目 xG 覆盖率仅约 41%（只有 API-Football 偶尔返回），现在由 Understat 免费、无限量补齐。

**API-Football 免费层只有 100 次/天**，本次接入后，历史批量回填和 xG 全部走免费源，
API-Football 只需承担它独有的 **控球率、传球成功率、积分榜、伤停**。

---

## 二、三个数据源如何协同（关键设计）

三个来源都只提供**队名**，而 ai-football 用 API-Football 的 `team_id`。
如果各自生成 fixture ID，同一场比赛会被写成两条记录，污染训练集。

因此抽出了**共享模块** `backend/app/services/fixture_matching.py`：

```
football-data.co.uk ─┐
                     ├─► fixture_matching.py ─► 同一个 team_id / 同一个 fixture_id
Understat ───────────┘
```

- **同一套队名解析**（`TeamResolver`，四级链路）
- **同一个合成 ID 公式**（键不含数据源前缀）：

  ```
  id = -(md5("{league_id}:{season}:{home_id}:{away_id}")[:15] % 2_000_000_000) - 1
  ```

  负数 ID 不占用 API-Football 的正整数空间；**同样输入永远得到同样 ID**。

→ **结果：Understat 的 xG 会挂到 football-data.co.uk 已建好的那场比赛上，不会重复建场；
两个任务的执行顺序完全无关紧要。**

### 队名解析四级链路

1. **精确匹配** `teams` 表（归一化：去重音/小写/去标点/剔除 `FC`/`AC`/`AS` 等后缀）
2. **别名表正向** `app/data/team_aliases.json`（外部名 → 规范名；规范名再模糊兜底）
3. **别名表反向**（当 `teams` 表里存的其实是短名时，用别名值反查）
4. **模糊匹配** `difflib.SequenceMatcher` ≥ 0.86

> 别名表两个数据源共用：fdco 用短名（`Man United`、`Nott'm Forest`、`Wolves`），
> Understat 用全称（`Manchester United`、`Nottingham Forest`、`Wolverhampton Wanderers`），
> 通过同一张表落到同一个 `team_id`。

---

## 三、Understat 接口要点（本次实测）

```
GET https://understat.com/getLeagueData/{slug}/{season}
```

- 接口已变更：**HTML 里不再内嵌 `JSON.parse` 数据**，必须走这个 AJAX 端点
- **必须带 `X-Requested-With: XMLHttpRequest` 头**，否则可能返回 HTML 页面
- 返回 **gzip 压缩 JSON**（httpx 自动解压，代码另有兜底）
- 顶层三键：`teams`(dict) / `players`(list) / **`dates`(list，比赛列表)**
- `dates[]` 每项：`isResult`、`h{id,title}`、`a{id,title}`、`goals{h,a}`、`xG{h,a}`、`datetime`（**UTC**）
- `isResult == false`（未开赛）没有 xG → 跳过

联赛映射与实测场次（**与 football-data.co.uk 完全一致**）：

| `league_id` | 联赛 | fdco 码 | Understat slug | 2024/25 场次 |
|---|---|---|---|---|
| 39 | 英超 | `E0` | `EPL` | 380 |
| 140 | 西甲 | `SP1` | `La_liga` | 380 |
| 78 | 德甲 | `D1` | `Bundesliga` | 306 |
| 135 | 意甲 | `I1` | `Serie_A` | 380 |
| 61 | 法甲 | `F1` | `Ligue_1` | 306 |
| 179 | 苏超 | `SC0` | **无覆盖** | — |

---

## 四、文件清单

### 新增（10 个）

| 文件 | 作用 |
|---|---|
| `backend/app/services/fixture_matching.py` | **共享**队名解析 / 合成 ID / 统计 upsert |
| `backend/app/services/football_data_service.py` | football-data.co.uk 采集器 |
| `backend/app/services/understat_service.py` | Understat 真实 xG 采集器 |
| `backend/app/services/injury_service.py` | API-Football 伤停采集器 |
| `backend/app/models/injury.py` | `injuries` 表模型 |
| `backend/app/data/team_aliases.json` | 148 条队名别名 |
| `backend/alembic/versions/c1f4a7b2d903_add_injuries.py` | 迁移（`down_revision=b6d2a8c9f001`） |
| `backend/tools/sync_football_data.py` | CLI |
| `backend/tools/sync_understat.py` | CLI |
| `backend/tools/sync_injuries.py` | CLI |
| `backend/docs/DATA_SOURCES.md` | 数据源详细文档 |

### 修改（6 个）

| 文件 | 改动 |
|---|---|
| `backend/app/core/config.py` | `+football_data_base_url`、`+understat_base_url` |
| `backend/.env.example` | 两个新环境变量 |
| `backend/app/models/__init__.py` | 注册 `Injury` |
| `backend/alembic/env.py` | **修了原版只导入 4 个模型的 bug** |
| `backend/app/services/scheduler.py` | `+football_data_backfill`(05:30)、`+understat_sync`(06:00)、`+injury_sync`(11:30) |
| `README.md` | 环境变量 / 任务表 / CLI / 数据源章节 |

---

## 五、使用方式

```bash
cd G:\polymarket\Sports\ai-football\backend

# 0) 新增 injuries 表，需要迁移
alembic upgrade head

# 1) 回填历史比赛与统计（免费、无限）
python tools/sync_football_data.py --seasons 2023 2024 2025
python tools/sync_football_data.py --dry-run        # 先看解析效果

# 2) 回填真实 xG（免费、无限）
python tools/sync_understat.py --seasons 2023 2024 2025
python tools/sync_understat.py --leagues 39 140     # 只跑英超+西甲
python tools/sync_understat.py --dry-run

# 3) 补 API-Football 独有的 3 项（按需，注意 100 次/天配额）
python tools/sync_fixtures.py

# 4) 伤停
python tools/sync_injuries.py --date 2026-10-07
python tools/sync_injuries.py --fixtures 1234567
```

**定时任务**（默认启用，可在 `scheduler_tasks` 表调整）：

| 任务 id | 名称 | 调度 |
|---|---|---|
| `football_data_backfill` | football-data.co.uk 回填 | 每天 05:30 |
| `understat_sync` | Understat xG 回填 | 每天 06:00 |
| `injury_sync` | 伤停数据同步 | 每天 11:30 |

> Understat 排在 fdco 之后，保证 `expected_goals` 以 Understat 为权威值。

---

## 六、验证结果（53 项断言全通过）

端到端测试：SQLite 建真表 + **真实网络**，五大联赛，约 3 分钟。

| 场景 | 结果 |
|---|---|
| **场景1** fdco→Understat（英超） | fdco 建 380 场 / 3040 条统计；Understat 新建 **0** 场、匹配 380、写 760 条 xG ✅ |
| 抽查 Man Utd vs Fulham | xG = 2.0427 / 0.4187（Understat 真值），比分 1-0（fdco） ✅ |
| **场景2** Understat→fdco（五大联赛） | Understat 先建 **1752** 场；fdco 新建 **0** 场、匹配 1752、xG 3504 条 ✅ |
| **顺序无关性** | 两种执行顺序下 EPL 380 个 `fixture_id` 与 `date` 映射**完全相同** ✅ |
| **幂等性** | 重跑 fdco/understat 均 0 新建、0 写入，表行数不变 ✅ |
| **精确 date 保护** | 预置 20:00 未被覆盖，xG 正确挂上 ✅ |
| **队名解析健壮性** | 短名场景 11/11；3 条 Understat 特有别名 4/4 ✅ |
| **特征兼容性** | `stat_type` 全部落在 `features.py` 白名单内 ✅ |
| 迁移链 | 25 个 revision，**单头 `c1f4a7b2d903`** ✅ |
| CLI / 调度器 | 3 个 CLI `--help` 正常；11 个任务注册正确 ✅ |

### 一个设计改进：日期升级规则

原方案「`date` 非空就不写」有副作用：fdco 先跑会写入 `00:00:00`（只有日期粒度），
Understat 的真实开球时间反而进不来。新规则：

- 已有值为空 → 写入
- 已有值恰为 `00:00:00` 且 Understat 有真实时间 → **升级**（仅当日期部分相同）
- 已有精确时间（来自 API-Football） → **永不覆盖**

→ 两种执行顺序**收敛到同一结果**（已逐场比对验证）。

---

## 七、已知限制与注意事项

1. **Understat 不覆盖苏超（179）**，该联赛 xG 只能靠 API-Football。
2. **fdco 只覆盖英格兰/苏格兰/五大联赛**，欧冠、南美等拿不到。
3. 早年 CSV 缺 `HST`/`AST`（射正）列时，对应统计会跳过。
4. 控球率、传球成功率、积分榜三项仍必须走 API-Football（100 次/天）。
5. **别名表可能需要按实际 `teams` 表补全**：本次的规范队名是依据 Understat 队名 +
   别名表推导的（无法在本地拿到真实 API-Football 队名表）。解析失败的队名会在同步
   日志和 CLI 输出里列出，补进 `app/data/team_aliases.json` 即可（键值都会归一化）。
6. 两个数据源都**不需要 key**，环境变量保留默认值即可。
