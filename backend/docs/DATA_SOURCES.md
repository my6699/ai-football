# 数据源说明

本项目原本只依赖 **API-Football** 一个数据源。本次新增了三个来源：

- **football-data.co.uk** —— 免费、无 key，用于批量回填历史比分与比赛统计；
- **Understat** —— 免费、无 key，用于补齐**真实 xG**；
- **API-Football `/injuries`** —— 补齐伤停数据（原项目未接入）。

## 数据源总览

| 数据源 | 是否需要 key | 覆盖联赛 | 提供内容 | 接入位置 |
|---|---|---|---|---|
| **API-Football** | 需要（`API_FOOTBALL_KEY`） | 全部已启用联赛 | 赛程、比分、半场比分、统计（含控球率/传球成功率/xG）、积分榜、阵容、事件、球员统计、赔率、伤停 | `fixture_service.py`、`standing_service.py`、`injury_service.py` |
| **football-data.co.uk** | **不需要** | E0/SP1/D1/I1/F1/SC0 | 比分、半场比分、射门、射正、角球、犯规、赔率 | `football_data_service.py` |
| **Understat** | **不需要** | 英超/西甲/德甲/意甲/法甲 | **真实 xG** | `understat_service.py` |

> 三个来源共用同一套「队名解析 + fixture 匹配」逻辑：`app/services/fixture_matching.py`。

## 为什么要加 football-data.co.uk

API-Football 免费层只有 **100 次/天**。回填历史数据时，每场比赛的统计都要单独调
一次 `/fixtures/statistics`，配额会瞬间耗尽。

football-data.co.uk 无 key、无次数限制，且联赛码与本项目的 `league_id` 一一对应：

| ai-football `league_id` | 联赛 | football-data.co.uk 码 | Understat slug |
|---|---|---|---|
| 39 | 英超 | `E0` | `EPL` |
| 140 | 西甲 | `SP1` | `La_liga` |
| 78 | 德甲 | `D1` | `Bundesliga` |
| 135 | 意甲 | `I1` | `Serie_A` |
| 61 | 法甲 | `F1` | `Ligue_1` |
| 179 | 苏超 | `SC0` | **无覆盖** |

## 三个数据源的分工

```
历史批量回填  ──►  football-data.co.uk（免费无限）
                    └─ fixtures            比分 / 半场比分
                    └─ fixture_statistics  射门 / 射正 / 角球 / 犯规

真实 xG       ──►  Understat（免费无限）
                    └─ fixture_statistics  expected_goals（主客各一条）

补剩下 3 项   ──►  API-Football（注意配额）
                    └─ /fixtures/statistics  控球率、传球成功率
                    └─ /standings            积分榜
                    └─ /injuries             伤停

当日 / 推理    ──►  API-Football
                    └─ /fixtures  /odds  /fixtures/lineups  /injuries
```

**football-data.co.uk 拿不到**：控球率、传球成功率、真实 xG、积分榜。
其中 **xG 已由 Understat 覆盖**；控球率、传球成功率、积分榜仍必须走 API-Football。

## 字段映射

### `fixtures`（football-data.co.uk）

| football-data.co.uk 列 | 目标字段 | 说明 |
|---|---|---|
| `Date` | `date` | `DD/MM/YYYY`（仅到天，**不覆盖**已有的精确开球时间） |
| `HomeTeam` / `AwayTeam` | `home_name` / `away_name` | 队名，需解析为 ID |
| `FTHG` / `FTAG` | `goals_home` / `goals_away` | 全场比分 |
| `HTHG` / `HTAG` | `halftime_home` / `halftime_away` | **半场比分**（`h_ht_gf5` 等特征的原料） |

### `fixtures`（Understat，仅在缺字段时兜底）

| Understat 字段 | 目标字段 | 说明 |
|---|---|---|
| `datetime` | `date` | UTC。空值直接补；若已有值只是 fdco 的「日期粒度」`00:00:00`，**升级**为真实开球时间（仅当日期部分相同）；已有精确时间**永不覆盖** |
| `goals.h` / `goals.a` | `goals_home` / `goals_away` | **只在比分为空时写**（Understat 不是比分权威源） |

> 日期升级规则让结果**与执行顺序无关**：无论 `football_data_backfill` 和
> `understat_sync` 谁先跑，最终 `date` 都是 Understat 的真实开球时间；
> 而 API-Football 写入的精确时间永远不会被降级。

### `fixture_statistics`

`stat_type` 命名刻意与 API-Football 对齐，以命中 `prediction/features.py` 的白名单
（`expected_goals` / `Total Shots` / `Shots on Goal` / `Ball Possession` /
`Corner Kicks` / `Passes %` / `Fouls`）：

| 来源 | 列 / 字段 | `stat_type` | 对应特征 |
|---|---|---|---|
| football-data.co.uk | `HS` / `AS` | `Total Shots` | `h_shots5` / `a_shots5` |
| football-data.co.uk | `HST` / `AST` | `Shots on Goal` | `h_shots_on5` / `a_shots_on5` |
| football-data.co.uk | `HC` / `AC` | `Corner Kicks` | `h_corners5` / `a_corners5` |
| football-data.co.uk | `HF` / `AF` | `Fouls` | `h_fouls5` / `a_fouls5` |
| **Understat** | `xG.h` / `xG.a` | **`expected_goals`** | **`h_xg5` / `a_xg5`** |

## Understat 接口细节

```
GET https://understat.com/getLeagueData/{slug}/{season}
```

- 必须带 `X-Requested-With: XMLHttpRequest`（否则可能返回 HTML 页面）；
- 返回 **gzip 压缩的 JSON**（httpx 会自动解压，代码里另有兜底）；
- 顶层三个键：`teams`(dict) / `players`(list) / **`dates`(list，比赛列表)**；
- `dates[]` 每项：`isResult`、`h{id,title}`、`a{id,title}`、`goals{h,a}`、
  `xG{h,a}`、`datetime`(UTC)；
- **`isResult == false` 的比赛（未开赛）没有 xG，直接跳过**；
- 实测每赛季场次：EPL 380 / La_liga 380 / Bundesliga 306 / Serie_A 380 / Ligue_1 306
  —— 与 football-data.co.uk 完全一致。

xG 以 4 位小数定长存储（如 `2.0427`），避免 Understat 原始 6 位有效数字带来的
无意义数值抖动。`features.py` 的 `parse_val` 会 `float()` 解析，精度无损。

### xG 权威性 / 执行顺序

`expected_goals` **以 Understat 为准**（`upsert_stat(overwrite=True)`）。若你同时
启用了 API-Football 的统计同步，请把 Understat 任务排在它**之后**执行
（默认调度已如此：`football_data_backfill` 05:30 → `understat_sync` 06:00）。

## 队名解析

外部数据源用**队名**，ai-football 用 **API-Football 的 `team_id`**。
`fixture_matching.TeamResolver` 按四级链路解析：

1. **精确匹配**：归一化后（去重音、小写、去标点、剔除 `FC`/`AC`/`AS`/`CD`/`SV` 等后缀）
   匹配 `teams` 表的 `name` 与 `name_zh`
2. **别名表正向**：`app/data/team_aliases.json`，外部名 → 规范名；
   若规范名仍匹配不到，会再对规范名做一次模糊匹配
3. **别名表反向**：当 `teams` 表里存的其实是别名表的**键**（短名）时，用别名值反查
4. **模糊匹配**：`difflib.SequenceMatcher` 相似度 ≥ `0.86`

> 别名表是**两个数据源共用**的。football-data.co.uk 用短名（`Man United`、
> `Nott'm Forest`、`Wolves`），Understat 用全称（`Manchester United`、
> `Nottingham Forest`、`Wolverhampton Wanderers`），两者通过同一张表落到同一个 `team_id`。

解析失败的队名会被收集，同步结束时在日志和 CLI 输出里列出，把它们补进
`app/data/team_aliases.json` 即可（键值都会做同样的归一化处理）。

## fixture ID 约定

API-Football 的 `fixtures.id` 是**正整数**。外部数据源独有的比赛
（DB 里还没有对应赛程）会用**确定性负数 ID** 新建：

```
id = -(md5("{league_id}:{season}:{home_id}:{away_id}")[:15] % 2_000_000_000) - 1
```

**键刻意不含数据源前缀**——这样 football-data.co.uk 和 Understat 对同一场比赛
算出**同一个 ID**，Understat 的 xG 会挂到 football-data.co.uk 已建好的那场比赛上，
而不是另建一条。两个数据源的执行顺序无关紧要，先跑谁都能对上。

匹配已有 fixture 的键是 `(league_id, season, home_id, away_id)`——主客必须一致，
不会把主客场颠倒的比赛错配到一起。

### 与 API-Football 的双向隔离（重要，关系到每日配额）

外部数据源建的是**负数 ID**，API-Football 用的是**正数 ID**。两侧都要做隔离，
否则会浪费配额或产生重复行。代码里已处理，共三处：

| 方向 | 风险 | 处理 |
|---|---|---|
| 负数 ID → API-Football | `sync_completed_sub_data` / `tools/sync_fixtures.py` / `tools/async_sync_subdata.py` 会为每场完赛比赛发起 4 次 `/fixtures/{events,lineups,statistics,players}` 请求。负数 ID 在 API-Football 里不存在 → **永远失败、永远不标记完成**，每轮都重来，持续烧掉 100 次/天的配额（`sync_fixtures.py` 甚至会死循环） | ① 外部 fixture 创建时直接置 `sub_data_synced=True`；② 上述三处的筛选条件加 `id > 0` 兜底 |
| 正数 ID → 已存在的负数行 | `sync_fixtures` / `sync_live_fixtures` 走 `_upsert_fixture`，原本只按 `fixtures.id` 查重。若 fdco 已建过这场（负数 ID），API-Football 再拉一次就会**插出第二行**，同一场比赛两条记录、污染训练集 | `_upsert_fixture` 增加自然键 `(league_id, season, home_id, away_id)` 去重：命中则**复用已有行**（保留负数 ID），只更新 API-Football 更精确的字段（date / status / referee 等） |

> 复用已有行意味着这些比赛的 `id` 保持为负 → 不会被送进 API-Football 的子数据端点。
> 这对预测管线**没有损失**：`prediction/features.py` 只读 `fixtures`、
> `fixture_statistics`、`standings` 三张表，不读 events / lineups / players。
> 而这三张表的内容，外部数据源已经写全（xG 由 Understat，比分/射门/角球/犯规由
> football-data.co.uk）。

## 使用

```bash
cd backend

# 1) 回填历史比赛与统计（免费，无配额限制）
python tools/sync_football_data.py --seasons 2023 2024 2025
python tools/sync_football_data.py --dry-run          # 先看看解析效果

# 2) 回填真实 xG（免费，无配额限制）
python tools/sync_understat.py --seasons 2023 2024 2025
python tools/sync_understat.py --leagues 39 140       # 只跑英超+西甲
python tools/sync_understat.py --dry-run

# 3) 补 API-Football 独有的 3 项（按需，注意配额）
python tools/sync_fixtures.py                          # 已有工具

# 4) 伤停
python tools/sync_injuries.py --date 2026-10-07
python tools/sync_injuries.py --fixtures 1234567

# 5) 建表（新增 injuries 表）
alembic upgrade head
```

## 定时任务

`app/services/scheduler.py` 已注册三个新任务（默认启用）：

| 任务 id | 名称 | 调度 |
|---|---|---|
| `football_data_backfill` | football-data.co.uk 回填 | 每天 05:30 |
| `understat_sync` | Understat xG 回填 | 每天 06:00 |
| `injury_sync` | 伤停数据同步 | 每天 11:30 |

可在 `scheduler_tasks` 表里调整或删除。`start_hour` 是 `DOUBLE`，支持 5.5 = 05:30
这样的分钟粒度。

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `FOOTBALL_DATA_BASE_URL` | `https://www.football-data.co.uk/mmz4281` | 保留默认即可 |
| `UNDERSTAT_BASE_URL` | `https://understat.com/getLeagueData` | 保留默认即可 |

两个数据源都**不需要 key**。

## 已知限制

- football-data.co.uk 的历史 CSV 一般只回溯到 1990 年代，且**只覆盖英格兰/苏格兰/
  五大联赛**，其他联赛（欧冠、南美等）拿不到。
- 早年的 CSV 缺少 `HST`/`AST`（射正）等列，此时对应统计会跳过（值为 `None`）。
- **Understat 不覆盖苏超（179）**，该联赛的 xG 只能靠 API-Football。
- Understat 的 `datetime` 是 UTC，只有「到秒」的粒度（实际只到分钟）。它会用来
  **升级** fdco 写入的日期粒度值，但**永不覆盖** API-Football 的精确开球时间。
- 控球率、传球成功率、积分榜三项仍必须走 API-Football（免费层 100 次/天）。
