# `APIs_report.md` 中哪些 API 可以给 ai-football 采集数据

> 目标：回答"polymarket-zero-cost-quant 项目里登记的那些 API，哪些能给 **ai-football** 供数"。
> 判据只有一个：**这个 API 能否产出 ai-football 训练/推理所需的那 78 个特征（或其原料）**。
> 数据来源：`APIs_report.md` + 两个项目的实际代码（已逐行核对，非只看文档）。

---

## 0. 先明确 ai-football 到底要什么数据

ai-football 的特征工程（`app/ml/features.py`）只从 **三张表** 取数，全部由 **API-Football v3** 灌入：

| 表 | 对应 API-Football 端点 | 提供什么 |
|---|---|---|
| `fixtures` | `/fixtures` | 主客队、比分 `goals_home/away`、**半场比分** `halftime_home/away`、日期、联赛、赛季 |
| `fixture_statistics` | `/fixtures/statistics` | `expected_goals`、`Total Shots`、`Shots on Goal`、`Ball Possession`、`Corner Kicks`、`Passes %`、`Fouls` |
| `standings` | `/standings` | `rank`、`points`、`goals_diff`、`all_played/win`、`home_played/win/goals_for/against`、`away_*` |

推理阶段（`app/ml/predict.py`）另外还调：`/odds`（赔率）、`/fixtures/lineups`（首发）、`/injuries`（伤停）。

**78 个特征按来源分成 4 组**（下文用这 4 组做覆盖判定）：

- **A 近期状态**（近 5/10 场胜平负、进失球、半场进失球、积分、主客场拆分、动量）≈ 47 个 → 原料 = `fixtures` 的比分 + 半场比分
- **B 比赛统计均值**（近 5 场 xG / 射门 / 射正 / 控球 / 角球 / 传球成功率 / 犯规）14 个 → 原料 = `fixture_statistics`
- **C H2H 交锋**（近 5 次）5 个 → 原料 = 历史比分（可自算）
- **D 积分榜**（排名、积分、净胜球、主客拆分、赛季排名差）12 个 → 原料 = `standings`
- **E 赛事背景** `is_cup` 1 个 → 联赛元数据

---

## 1. 结论速览

| # | API | 能给 ai-football 供数？ | 覆盖度 | 说明 |
|---|---|---|---|---|
| 4 | **API-Football**（v3.football.api-sports.io） | ✅✅✅ **首选·完整** | **~100%** | ai-football 的原生数据源，三张表全包 + 赔率/伤停/首发。两个项目都已有 key |
| 5 | **football-data.co.uk** | ✅✅ **免费主力** | **~70%** | 无 key，覆盖 ai-football 的 5 大联赛；缺控球率、传球成功率、真实 xG、积分榜 |
| 8 | **ESPN News** | ⚠️ 仅辅助 | 0%（不进 78 特征） | 只有英超新闻，仅能做 LLM 软信息层 |
| 2 | **The Odds API** | ⚠️ 仅辅助 | 0%（不进 78 特征） | 只有 Pinnacle h2h 赔率，78 特征里没有赔率项 |
| 1 | Polymarket（Gamma/CLOB） | ❌ 无关 | 0% | 预测市场价格，不是足球事实数据 |
| 3 | Balldontlie | ❌ 无关 | 0% | 仅 NBA/WNBA/NFL/MLB |
| 6 | TennisMyLife | ❌ 无关 | 0% | 网球 |
| 7 | SportScore | ❌ 无关 | 0% | 网球赛程 |
| 9 | Google Gemini | ❌ 无关 | 0% | LLM，不是数据源 |
| 10 | 企业微信 Webhook | ❌ 无关 | 0% | 通知通道 |
| 11 | nba_api | ❌ 无关 | 0% | NBA 备选源 |

**一句话**：真正能用的是 **API-Football（完整）** 和 **football-data.co.uk（免费、约七成）**；ESPN 新闻 / The Odds API 只能做辅助；其余全部与足球无关。

---

## 2. 逐特征覆盖矩阵（78 特征 × 数据源）

✅ = 直接提供　🟡 = 可推导/代理　❌ = 拿不到

| 特征组（数量） | API-Football | football-data.co.uk | 备注 |
|---|---|---|---|
| **A. 近期状态** 胜平负/进失球/积分/动量（~35） | ✅ `/fixtures` | ✅ `FTHG/FTAG` | 两边都行，football-data 更省事 |
| **A. 半场进失球** `h_ht_gf5/h_ht_ga5/a_ht_gf5/a_ht_ga5`（4） | ✅ `/fixtures` | ✅ `HTHG/HTAG` | football-data.co.uk **有半场比分** |
| **A. 主客场拆分** `h_home_*/a_away_*`（6） | ✅ | ✅ | 由比分按主客场聚合 |
| **A. 动量/近5场结果序列** `h_momentum/h_result_1..5`（12） | ✅ | ✅ | 序列自算 |
| **B. 射门** `h_shots5/a_shots5` | ✅ `Total Shots` | ✅ `HS/AS` | |
| **B. 射正** `h_shots_on5/a_shots_on5` | ✅ `Shots on Goal` | ✅ `HST/AST` | |
| **B. 角球** `h_corners5/a_corners5` | ✅ `Corner Kicks` | ✅ `HC/AC` | |
| **B. 犯规** `h_fouls5/a_fouls5` | ✅ `Fouls` | ✅ `HF/AF` | |
| **B. 控球率** `h_possession5/a_possession5` | ✅ `Ball Possession` | ❌ **无此列** | football-data.co.uk 唯一硬伤之一 |
| **B. 传球成功率** `h_passes_pct5/a_passes_pct5` | ✅ `Passes %` | ❌ **无此列** | football-data.co.uk 唯一硬伤之二 |
| **B. xG** `h_xg5/a_xg5/xg_diff5` | ✅ `expected_goals`（部分联赛） | 🟡 仅 `射正×转化率` 代理 | 真实 xG 建议走 API-Football 或 Understat |
| **C. H2H** `h2h_*`（5） | ✅ 历史比分自算 | ✅ 历史比分自算 | 两个源都能算 |
| **D. 积分榜** `h_rank/h_points/h_goals_diff/.../rank_diff`（12） | ✅ `/standings` | 🟡 可用历史比分**自建**（注意赛季过滤！） | football-data.co.uk 无现成积分榜 |
| **E. 赛事背景** `is_cup` | ✅ 联赛元数据 | ✅ 联赛码映射 | |

**覆盖率**：API-Football ≈ **100%**；football-data.co.uk ≈ **70%**（丢控球率、传球成功率、真实 xG、现成积分榜 4 项，共 18 个特征受影响）。

---

## 3. 首选方案：API-Football（完整复用）

**为什么是它**：ai-football 本来就是用 API-Football 建的三张表；polymarket 项目的 `config/secrets.yaml` 里 `api_football_key` **也已配置**（它只用到了 `/injuries` 一个端点）。所以这是"**同一把钥匙，多开几扇门**"，无需新增任何账号。

| 需要的端点 | polymarket 项目现状 | ai-football 用途 |
|---|---|---|
| `/fixtures` | 未使用 | A 组全部状态特征 |
| `/fixtures/statistics` | 未使用 | B 组统计特征（**含控球/传球%/xG**） |
| `/standings` | 未使用 | D 组积分榜特征 |
| `/odds` | 未使用（改用 The Odds API） | 赔率 |
| `/injuries` | ✅ 已用（`free_injury_collector.py`） | 伤停软信息 |
| `/fixtures/lineups` | 未使用 | 首发 |

**唯一约束**：免费层 **100 次/天**。78 特征要覆盖 5 大联赛 × 多个赛季，历史回填会很快烧完配额——建议：
- 历史数据一次性回填后**落库**（ai-football 已是 MySQL 架构），不要每次重拉；
- 或用下面的 football-data.co.uk 承担历史回填，API-Football 只拉"它独有的"（控球/传球%/xG/积分榜）。

---

## 4. 免费主力：football-data.co.uk（省 key 的七成）

**实测列（`2425/E0.csv` 表头，已核实）**：

```
Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HTR,Referee,
HS,AS,HST,AST,HF,AF,HC,AC,HY,AY,HR,AR,
B365H..PSH,PSD,PSA..(多家赔率),...(大小球/亚盘)
```

- **比分**：`FTHG/FTAG` → A 组
- **半场比分**：`HTHG/HTAG` → `h_ht_gf5` 等 4 个特征 ✅（这是很多人以为它没有、其实有的）
- **射门/射正**：`HS/AS`、`HST/AST` → B 组
- **角球/犯规**：`HC/AC`、`HF/AF` → B 组
- **赔率**：`PSH/PSD/PSA`（Pinnacle）→ 可直接替代 The Odds API 的历史赔率
- **联赛码与 ai-football 联赛完全对齐**：`E0↔39`、`SP1↔140`、`D1↔78`、`I1↔135`、`F1↔61`

**拿不到的 4 项**：控球率、传球成功率、真实 xG、现成积分榜。

**两个必须注意的坑**：
1. **积分榜要自建**，且**必须按 `season` 过滤**——这正是第一阶段在 ai-football 里查出的那个 bug（整合式积分榜 join 漏了赛季过滤，导致测试集 28.9% 行膨胀、37.3% 重复比赛预测矛盾）。自建时务必 `group by (team, season)`。
2. **xG 只有代理**：polymarket 项目现有实现是 `xG = 射正数 × (联赛总进球/联赛总射正)`，是**粗糙代理**，不等于真实 xG。若要保留 ai-football 的 `h_xg5` 质量，B 组 xG 应走 API-Football 或 Understat。

---

## 5. 辅助项（不进 78 特征）

| API | 能做什么 | 不能做什么 |
|---|---|---|
| **ESPN News**（§8） | 抓 `soccer/eng.1` 英超新闻/伤停文字，喂给 LLM 做 ΔP 修正 | 不进 78 特征；只有英超，无西甲/德甲/意甲/法甲 |
| **The Odds API**（§2） | 拉 Pinnacle h2h 公平概率，做赛后**价值下注/Edge 对照** | 78 特征里没有任何赔率项，训练用不上 |
| **Polymarket**（§1） | 提供"市场隐含概率"，可作 ai-football 预测的**外部基准**（模型 vs 市场） | 是市场价格不是足球事实，不能当特征 |
| **Google Gemini**（§9） | 与 ai-football 自己的 DeepSeek 同层，做软信息修正 | 不是数据源 |

---

## 6. 与 ai-football 现有链路的对接建议

```
              ┌─ API-Football ─ /fixtures ──────┐
              │                /fixtures/statistics │──► fixture_statistics 表
              │                /standings ──────────┤──► standings 表
              │                /odds /injuries      │
              └────────────────────────────────────┘
历史回填 ──► football-data.co.uk CSV ──► fixtures 表（比分/半场/射门/射正/角球/犯规 + 赔率）
                                        └─ 自建积分榜（务必按 season 过滤）
可选增强 ──► Understat ──► 真实 xG 替换代理 xG
```

- **历史批量回填**：用 **football-data.co.uk**（免费、无限次、覆盖 5 大联赛）灌 `fixtures` 与大部分 `fixture_statistics`。
- **补 4 项独有字段**（控球率、传球成功率、真实 xG、积分榜）：用 **API-Football**，按"每场一次"精打细算配额。
- **推理/当日**：`/fixtures`（今日赛程）+ `/odds` + `/injuries` + `/fixtures/lineups`。
- **可选**：接 **Understat** 把 `h_xg5/a_xg5/xg_diff5` 从代理升级为真实 xG（polymarket 项目 config 里 `use_understat: true` 但代码未接线，需自行接）。

---

## 7. 一句话总结

在 `APIs_report.md` 登记的 11 类 API 里，**只有 2 个能真正给 ai-football 供数**：
**API-Football（完整、复用现成 key）** 与 **football-data.co.uk（免费、约七成、覆盖同 5 大联赛）**；
ESPN 新闻与 The Odds API 仅作辅助；Polymarket / Balldontlie / 网球 / nba_api / Gemini / 企业微信 与足球特征无关。
