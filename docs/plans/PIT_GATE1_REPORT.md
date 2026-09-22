# PIT Gate 1 完成报告

- 状态：**Gate 1 已通过**（冻结，不修改 PIT 逻辑）
- 报告日期：2026-09-23
- 设计依据：`PIT_FROZEN_SPEC.md` v1.1（冻结）+ `docs/data/ACQUISITION_COMPLETION_AUDIT.md`
- 运行环境：Python 3.13.9 · pandas 2.3.3 · backtrader 1.9.78.123 · conda `base`
- 范围：仅 PIT 数据层 / 时间语义 / 回测执行因果链。**未触碰 Regime / Portfolio / Risk 决策逻辑与参数。**

---

## 1. 最终测试结果（冻结）

```
tests/data  →  28 passed, 0 failed, 0 skipped  (pytest, 26.6s)
```

P0 核心测试全部为真实断言，**无 importorskip 跳过 P0**（仅 backtrader 相关测试在缺少依赖时 skip，但完整依赖环境已安装，实际未 skip）。

分项：

| 测试文件 | 数量 | 覆盖 |
|---|---|---|
| `test_contracts.py` | 8 | tz-aware UTC、DST/标准时收盘、开盘时刻、naive 拒绝、因果不变量违规 |
| `test_historical_mode.py` | 4 | 历史模式网络守卫（requests / Session / 恢复 / 构造器激活） |
| `test_historical_store.py` | 9 | 行情无前视、盘中排除 T 收盘、非交易日无 bar、新闻未来排除、基本面无前视、restatement 版本选择、交易日历周末/假日、2025-01-09 特殊休市、快照哈希确定性 |
| `test_historical_context.py` | 5 | 每标的分文件、未来信号排除、同日信号排除、最新在前有界、`read_historical_context` 函数 |
| `test_execution_t1.py` | 2 | T 收盘 → T+1 开盘成交、每个 fill 的因果不变量 |

---

## 2. 修改文件清单（Gate 1 PIT 范围）

**新增**

| 文件 | 说明 |
|---|---|
| `src/data/contracts.py` | 冻结时间契约：`ensure_utc` / `close_time_utc` / `open_time_utc` / `validate_causal_order` / `PITTimeError` |
| `src/data/historical_mode.py` | 全局网络守卫：`enable/disable_historical_mode` + `HistoricalModeViolation`（patch `requests.Session.request` 与 `aiohttp.ClientSession._request`） |
| `src/data/historical_store.py` | 四个 PIT 接口 + `SPECIAL_CLOSURES` 特殊休市表 + `snapshot_hash` |
| `conftest.py` | repo 根加入 `sys.path` |
| `tests/data/conftest.py` | 每测试前后清理历史模式守卫 |
| `tests/data/test_contracts.py` | 时间契约测试 |
| `tests/data/test_historical_mode.py` | 网络守卫测试 |
| `tests/data/test_historical_store.py` | PIT 存储测试 |
| `tests/data/test_historical_context.py` | 历史上下文过滤测试 |
| `tests/data/test_execution_t1.py` | T+1 执行测试 |

**修改**

| 文件 | 变更 |
|---|---|
| `src/agents/portfolio_manager_agent.py` | 修复 `read_historical_context`：改读 `daily_analysis_{symbol}.csv`，按 `symbol` 过滤，`date < analysis_date` 严格先于，最新在前取 `portfolio_historical_context_count` |
| `src/backtesting/strategies.py` | `PrimoAgentStrategy` 增加 `execution_log`/`trade_log`/`_order_signal_date`；`notify_order` 记录订单级时间与价格并调用 `validate_causal_order`；`next()` 显式 `bt.Order.Market` |
| `src/backtesting/engine.py` | `cerebro.broker.set_coc(False)`（显式关闭 cheat-on-close） |

---

## 3. PIT 不变量 → 代码位置映射

| 不变量 | 代码位置 |
|---|---|
| 四时间字段 tz-aware UTC | `src/data/contracts.py:UTC` + `ensure_utc()` |
| 拒绝 naive / 本地时间 | `contracts.py:ensure_utc` 抛 `PITTimeError` |
| `feature_as_of <= signal_generated_at < execution_at` | `contracts.py:validate_causal_order`（左 `<=`，右严格 `<`）；`strategies.py:notify_order` 每次 fill 调用 |
| 行情 bar 按收盘可见性 `close_time_utc(T) <= as_of` | `historical_store.py:get_market_window`（`df["known_at"] = close_time_utc(date)`，`df[df["known_at"] <= a]`） |
| 新闻 `available_at <= as_of` | `historical_store.py:get_news_events` |
| 基本面先披露时间过滤再选最新有效版本 | `historical_store.py:get_fundamentals`（先 `known_at <= a`，再 `groupby(["concept","unit","end"]).tail(1)`） |
| `retrieved_at` 永不进决策 | 全部接口无 `retrieved_at` 过滤；仅存在于审计/溯源 |
| 历史模式禁网 | `historical_mode.py` + `HistoricalDataStore.__init__`（historical 模式激活守卫） |
| T+1 开盘成交（无同 bar 成交） | `engine.py:set_coc(False)` + `strategies.py` Market order |
| 确定性快照 | `historical_store.py:snapshot_hash`（行/列序无关 sha256） |

---

## 4. AAPL 历史日期完整 PIT 查询链

以 `feature_as_of = 2025-01-03T21:00:00Z` 为例：

1. `get_market_window("AAPL", as_of, lookback_days=30)` → 仅返回 `close_time_utc(T) <= 2025-01-03T21:00Z` 的日线 bar，末 bar 不晚于 `2025-01-03`。
2. `get_news_events("AAPL", as_of, lookback_days=365)` → 仅 `available_at <= as_of`。
3. `get_fundamentals("AAPL", as_of)` → 先 `known_at <= as_of`，再按 `(concept, unit, end)` 取 `known_at` 最新版本。
4. `read_historical_context("AAPL", "2025-01-03")` → `daily_analysis_AAPL.csv` 中 `date < 2025-01-03` 的最新 N 条。

关键证据：`test_fundamentals_restatement_version_selection` 证实 AAPL `AccountsPayableCurrent/USD/end=2017-09-30` 在 restatement（2018-11-05）前返回 `49,049,000,000.0`，其后返回 `44,242,000,000.0` —— 未回填未来修正值。

---

## 5. T → T+1 真实成交日志（Backtrader 实际产出）

```
signal BUY on 2025-02-11 (T close $232.62)
order   BOUGHT 128 shares @ $232.62        # 订单在 T 收盘时提交（参考价）
exec    EXEC BUY 128 @ $231.20 on 2025-02-12   # T+1 开盘成交
        feature_as_of       = 2025-02-11T21:00:00+00:00
        execution_at        = 2025-02-12T14:30:00+00:00
        fill_price 231.20  !=  T close 232.62   → 证明非同 bar 成交
```

`test_execution_t1.py` 的确定性断言同样验证：BUY 信号 T=2024-01-02 在 T+1 开盘 `101.0` 成交，而非 T 收盘 `105.0`。

---

## 6. 49 条非交易日旧信号调查结果（只调查，未删除/修改旧结果）

- 结论：49 条非 SPY 交易日信号 = **7 只标的 × 7 个假日**。
- 7 只标的：AAPL / AMZN / JNJ / META / NFLX / TSLA / WMT。
- 7 个假日日期：2025-01-01、2025-01-09（Carter 哀悼日）、2025-01-20、2025-02-17、2025-04-18、2025-05-26、2025-06-19。
- 处理：仅出报告，旧结果原样保留；`get_trading_calendar` 已通过 `SPECIAL_CLOSURES` 冻结 2025-01-09 并新增 `test_trading_calendar_special_closure` 守护。

---

## 7. Technical debt / P1（本阶段不修复，记录在案）

| 项 | 分类 | 说明 | 处置 |
|---|---|---|---|
| 循环导入 `portfolio_manager_agent → workflows.state → workflow → agents` | Technical debt | 预存在架构问题；测试端以先 `import src.workflows.workflow` 打破，未动生产架构 | 后续重构，Gate 1 不修 |
| Tiingo raw OHLC 拆股断点 | **P1 §5.1** | 当前消费未复权价；NVDA 2024-06-10 10:1 拆股会污染技术指标（数据正确性问题，非前视） | 独立 corporate action 表，按 `feature_as_of` 应用调整 |
| Early close / 非常规临时休市 | **P1 §5.3** | 半天早收会话（2025-07-03、2025-11-28、2025-12-24）尚未建模；`SPECIAL_CLOSURES` 已覆盖 2025-01-09 全天闭市 | 基于公告日构建，避免「用今日日历冒充 T 时点已知日历」 |

---

## 8. 建议 git commit / tag

Gate 1 变更建议一次性提交并打 tag（**待确认，未执行**）：

```bash
git add -A
git commit -m "$(cat <<'EOF'
feat(pit): Gate 1 — point-in-time data layer and T+1 execution causality

Implement the four frozen PIT query interfaces over local data only,
enforce tz-aware UTC + feature_as_of<=signal<execution invariant,
fix read_historical_context, and record T close -> T+1 open fills.

28 passed, 0 failed, 0 skipped (tests/data).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git tag -a gate1-pit-passed -m "PIT Gate 1 passed: 28/0/0"
```

---

## 9. 尚未解决的 P1/P2 风险（保留，不阻塞 Gate 1）

- P1：corporate actions（Tiingo raw 拆股断点）、SEC 完整版本链、early close/临时休市。
- P2：PIT universe 幸存者偏差、退市股票、历史行业归属、分析师一致预期。
- 详见 `PIT_FROZEN_SPEC.md` §5 / §6。
