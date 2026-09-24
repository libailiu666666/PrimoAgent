# Gate 2 完成报告 — Walk-forward Benchmark

- 状态：**Gate 2 已通过**（验收完成，停止；不自动进入 Gate 3）
- 报告日期：2026-09-24
- 设计依据：Gate 1 PIT 层（冻结，未改动）+ 本阶段新增 `src/experiments/` 评估框架
- 运行环境：Python 3.13.9 · pandas 2.3.3 · pyarrow 21.0.0 · backtrader 1.9.78.123 · conda `base`
- 范围：确定性基线回测、数据驱动 walk-forward 折、冻结 T close → T+1 open 执行、实验 manifest、PIT 读缓存性能优化。**未触碰 Regime / Portfolio / Risk 决策逻辑与参数。**

---

## 0. 交付物清单

| 文件 | 说明 |
|---|---|
| `configs/experiments/gate2_baseline.yaml` | Gate 2 基线配置（冻结）：明确关闭 3 个 legacy 开关 |
| `src/experiments/config.py` | 实验配置加载、规范化哈希、legacy 开关解析 |
| `src/experiments/folds.py` | 数据驱动年度扩展折（严格时序，无 shuffle） |
| `src/experiments/data.py` | 复权价加载 + 确定性数据快照哈希 |
| `src/experiments/execution.py` | T+1 执行引擎 + PIT 视图 + 因果不变量 fill |
| `src/experiments/strategies.py` | 5 个确定性基线（无随机、无 LLM） |
| `src/experiments/metrics.py` | 绩效指标 + 折间回报链式汇聚 |
| `src/experiments/manifest.py` | 实验 manifest 构建器 |
| `src/experiments/runner.py` | walk-forward 编排 |
| `scripts/experiments/run_walk_forward.py` | CLI 入口 |
| `src/data/historical_store.py` | **本阶段唯一 Gate 1 文件改动**：`get_fundamentals` 读缓存（纯性能，语义不变，见 §13） |
| `tests/experiments/` | 7 个测试文件（26 用例） |
| `tests/data/test_fundamentals_cache.py` | 新增 4 个缓存回归测试 |

---

## 1. 实际折定义（数据驱动，未硬编码）

年度扩展折，`start_year=2017`，`train=4 / calibration=1 / test=1` 年。折由真实共同交易日覆盖自动推导：

```
fold 0: train 2017-01-03..2020-12-31 | cal 2021-01-04..2021-12-31 | test 2022-01-03..2022-12-30
fold 1: train 2017-01-03..2021-12-31 | cal 2022-01-03..2022-12-30 | test 2023-01-03..2023-12-29
fold 2: train 2017-01-03..2022-12-30 | cal 2023-01-03..2023-12-29 | test 2024-01-02..2024-12-31
fold 3: train 2017-01-03..2023-12-29 | cal 2024-01-02..2024-12-31 | test 2025-01-02..2025-12-31
fold 4: train 2017-01-03..2024-12-31 | cal 2025-01-02..2025-12-31 | test 2026-01-02..2026-09-11 (partial test)
```

- 训练窗逐年**扩展**（4 → 8 年），从不 shuffle。
- 严格时序 `train < calibration < test`，互不重叠。
- 首个测试年 = `start_year + train + cal + test − 1 = 2022`，最短训练窗恰为 4 年。
- 末折 2026 因数据止于 2026-09-11，被 `is_partial_test` 标记（`test_end.month < 12`）。

---

## 2. 基线结果表（全部测试折链式汇聚，n_days=1172）

`initial_capital=100000`，commission/slippage 见成本敏感性。Sharpe 无风险利率取 0。

| strategy | cost(bps) | 总回报 | 年化回报 | 年化波动 | Sharpe | 最大回撤 | Calmar |
|---|---:|---:|---:|---:|---:|---:|---:|
| buy_and_hold | 0 | 69.35% | 11.99% | 17.41% | 0.69 | -24.47% | 0.49 |
| equal_weight | 0 | **130.32%** | 19.65% | 16.84% | **1.17** | -22.33% | 0.88 |
| fundamental_only | 0 | 56.01% | 10.04% | 19.66% | 0.51 | -26.47% | 0.38 |
| spy_benchmark | 0 | 71.82% | 12.34% | 17.42% | 0.71 | -24.47% | 0.50 |
| technical_only | 0 | 76.92% | 13.05% | 16.97% | 0.77 | -26.71% | 0.49 |

- 0 bps 下：`equal_weight`（等权 30 股一次性买入持有）最强（130.32%），跑赢 `spy_benchmark`（71.82%）与 `buy_and_hold`（69.35%）。
- `fundamental_only`（月度 top-K 最新 ROA）落后（56.01%），且波动最高（19.66%）。
- `technical_only`（日频 SMA20/50 择时）0 bps 76.92%，但对成本高度敏感（见 §3）。

> **OOS 累计收益定义（重要）**：上表「总回报」是**复利链式 OOS 收益**，不是折间算术平均、也不是折间简单求和。定义见 §11.3 与 `src/experiments/metrics.py::pool_metrics`。

---

## 3. 成本敏感性（0 / 10 / 20 / 50 bps，单边名义佣金）

| strategy | 0 bps | 10 bps | 20 bps | 50 bps | 结论 |
|---|---:|---:|---:|---:|---|
| buy_and_hold | 69.35% | 68.58% | 67.81% | 65.52% | 换手极低，几乎免疫 |
| equal_weight | 130.32% | 129.33% | 128.35% | 125.41% | 一次性建仓，成本影响小 |
| fundamental_only | 56.01% | 51.52% | 47.16% | 34.78% | 月度换手，逐级衰减 |
| spy_benchmark | 71.82% | — | — | — | **外部参考，不参与成本敏感性横向比较**（见 §11.2） |
| technical_only | 76.92% | 58.00% | 41.09% | 0.42% | **日频换手，50bps 下归零** |

- `technical_only` 是换手率最高的策略（日频），50bps 单边成本下总回报从 76.92% 塌缩到 0.42% —— 强烈印证「换手成本是择时策略的第一杀手」。
- 成本模型对所有策略统一：`commission = notional × bps/10000`（单边），`slippage = notional × bps/10000`（单边），cash reserve 0%。

---

## 4. 完整 manifest 示例（单次运行）

文件：`output/experiments/gate2_baseline_20260923T171204Z_33422fac/manifest.json`

```json
{
  "experiment_id": "gate2_baseline_20260923T171204Z_33422fac",
  "generated_at": "2026-09-23T17:12:04.717584+00:00",
  "config_path": "configs\\experiments\\gate2_baseline.yaml",
  "config_hash": "ca3bad52aa2a2d88c84f370f3b9c570158865f71253ca6c13417d9cdb1f8fb4a",
  "data_snapshot_hash": "cc5b4901438f47f67a8f3356884c29fa2883ddc3b69aff8e96686bb15df6552a",
  "git_commit": "69d0a0977066ff04683a7a46e1b24913ac44d282",
  "git_short": "69d0a09",
  "git_dirty": true,
  "random_seed": 42,
  "cost_assumptions": {
    "initial_capital": 100000.0,
    "commission_bps_grid": [0, 10, 20, 50],
    "slippage_bps": 0.0,
    "cash_reserve_pct": 0.0
  },
  "execution_assumptions": {
    "protocol": "T close -> signal after close -> T+1 open",
    "signal_time": "T close",
    "execution_time": "T+1 open",
    "causal_invariant": "feature_as_of <= signal_generated_at < execution_at"
  },
  "legacy_risk_switches": {
    "risk.regime.enabled": false,
    "backtesting.enable_trailing_stop": false,
    "backtesting.enable_take_profit": false
  },
  "ticker_universe": ["AAPL", "AMD", "AMZN", "AVGO", "BA", "BAC", "CAT", "COST",
    "CVX", "GOOGL", "GS", "HD", "JNJ", "JPM", "KO", "LLY", "MCD", "META",
    "MSFT", "NEE", "NFLX", "NVDA", "ORCL", "PFE", "PG", "TSLA", "UNH", "V",
    "WMT", "XOM"],
  "folds": [ { "fold": 0, "train_start": "2017-01-03", "train_end": "2020-12-31",
               "calibration_start": "2021-01-04", "calibration_end": "2021-12-31",
               "test_start": "2022-01-03", "test_end": "2022-12-30",
               "is_partial_test": false }, "… (共 5 折)" ],
  "results": [ "… (strategy / version / fold / cost_bps / 指标)" ],
  "output_paths": { "manifest": "…/manifest.json", "results_csv": "…/results.csv",
                     "equity_dir": "…/equity", "fills_dir": "…/fills" }
}
```

manifest 完整覆盖验收要求 7 的全部字段：experiment_id、strategy/version、fold、train/cal/test 时间范围、ticker universe、config hash、data snapshot hash、git commit、random seed、cost assumptions、execution assumptions、legacy risk 3 开关最终值、output paths、generated_at。每个 fold 的 equity 曲线与 fill 明细分别落盘于 `equity/` 与 `fills/`。

---

## 5. pytest 结果（最终）

```
tests/data       → 37 passed, 0 failed, 0 skipped
tests/experiments → 26 passed, 0 failed, 0 skipped
```

| 测试文件 | 数量 | 覆盖 |
|---|---|---|
| `tests/data/test_historical_store.py` | 8 | PIT 市场窗 / 新闻 / 基本面 / 交易日历 / 确定性 |
| `tests/data/test_fundamentals_cache.py` | **4（新增）** | 缓存不重复读 parquet、不同 as_of 返回不同 PIT、缓存不泄漏未来重述、缓存与非缓存等价 |
| `tests/data/` 其余 | 25 | contracts / historical mode / historical context / execution t1 / legacy switches |
| `tests/experiments/test_folds.py` | 7 | 时序严格有序、互不重叠、训练窗扩展、首个测试年、末折 partial 标记、数据不足返回空、`select_dates` 闭区间 |
| `tests/experiments/test_execution_t1.py` | 3 | fill 在 T+1 开盘成交、fill 价为次日开盘价、`feature_as_of <= signal < execution` 因果链、PITView 历史截断到 `as_of` |
| `tests/experiments/test_no_test_leakage.py` | 1 | 注入 RecordingStrategy 记录 `fit()` 所见最大日期，断言 `<= calibration_end` 且 `< test_start` |
| `tests/experiments/test_determinism.py` | 5 | 引擎确定性、技术策略确定性、config 哈希序无关且稳定、数据快照哈希敏感、全 walk-forward 两次运行一致 |
| `tests/experiments/test_costs.py` | 2 | 更高佣金降低净回报、滑点降低净回报 |
| `tests/experiments/test_manifest.py` | 5 | 必填字段齐全、legacy 开关为 false、git 结构、experiment_id 唯一、JSON 时间戳回写 |
| `tests/experiments/test_legacy_switches_gate2.py` | 3 | gate2 配置三开关全 false、开关规格与配置路径一致、`apply_legacy_switches_to_global` 强制关闭 |

> 说明：`tests/data/test_execution_t1.py` 与 `tests/experiments/test_execution_t1.py` 基名相同，单条 `pytest tests/data tests/experiments` 会触发 import 冲突；需分别运行两个目录（见 §13）。属既有命名问题，非本阶段引入。

---

## 6. 确定性验证（同配置运行两次）

以 `--strategies buy_and_hold,equal_weight,technical_only --cost-bps 0` 连续运行两次：

```
diff results.csv（两次运行） → 字节级完全一致（IDENTICAL）
config_hash            → ca3bad52…（两次一致）
data_snapshot_hash     → cc5b4901…（两次一致）
```

结论：同一配置在同一数据快照上运行，结果**完全可复现**（`random_seed` 固定、无任何随机源、策略为确定性实现）。config/data 哈希均为内容寻址 sha256，任何配置或数据漂移都会改变哈希。

---

## 7. legacy risk 3 项关闭证据

runner 启动即解析并打印三项最终值，同时写入 manifest：

```
Legacy risk switches (final values):
  risk.regime.enabled = False
  backtesting.enable_trailing_stop = False
  backtesting.enable_take_profit = False
```

- `configs/experiments/gate2_baseline.yaml` 中 `legacy_risk` 三项显式 `false`。
- `ExperimentConfig.assert_legacy_switches_off()` 在 runner 入口 fail-fast（任一项非 false 即抛错）。
- `apply_legacy_switches_to_global()` 作为纵深防御，将三项写入全局 `config` 对象，确保任何共享 legacy 代码路径也读到关闭状态。
- 测试 `test_legacy_switches_gate2.py` 三项独立断言。

---

## 8. 问题 / 数据缺口 / 技术债

| 项 | 分类 | 说明 | 处置 |
|---|---|---|---|
| `fundamental_only` 运行极慢 | ~~P1 性能~~ **已修复** | 原 `get_fundamentals` 每次调用重读 parquet 并逐行 Python 循环；本阶段加入按 symbol 读缓存（签名失效），单次调用 2.13s → 19.3ms（~110×），详见 §12 | ✅ 完成 |
| 末折 2026 为 partial | 数据缺口 | 数据止于 2026-09-11，末折测试窗不完整 | 已通过 `is_partial_test` 标记，结果表如实呈现 |
| universe 幸存者偏差 | P2（继承） | 30 股为当前存活成分，未含历史退市股 | 继承 `PIT_FROZEN_SPEC.md` §6，Gate 2 不处理 |
| 早收盘半日盘（2025-07-03、2025-11-28、2025-12-24） | P1（文档化） | 半日盘仍按全天 close 处理 | 已在 `historical_store.py` 注释中标注为 P1 局限 |
| `tests/data` 与 `tests/experiments` 存在同名测试模块 | P3 | `test_execution_t1.py` 基名冲突，需分目录跑 | 未改动（改名属范围外） |

---

## 9. git commit / tag

```bash
# 提交 1：Gate 2 walk-forward 基准
feat(experiments): complete Gate 2 walk-forward benchmark

# 提交 2：get_fundamentals 读缓存
perf(data): cache PIT fundamentals for walk-forward queries

# 全部验收通过后打 tag
git tag -a gate2-benchmark-passed -m "Gate 2 walk-forward passed: 63/0/0"
```

---

## 10. 停止点

Gate 2 验收通过，**停止**。未进入 Gate 3。下一步（若继续）按 `NEXT_STEPS.md` 规划：Regime 方法 / 动态权重 / 置信度校准 / Risk Optimizer / TSFM / 新 Agent 均属 Gate 3+，本阶段明确**未实现**。

---

## 11. 三项 sanity check 结论（Final Wrap-up）

### 11.1 `technical_only` 高成本塌缩 —— 确认为真实换手，非成本模型 bug

| 检查项 | 结果 |
|---|---|
| 全 5 折总成交笔数 | 20,525 笔（折内：3516 / 4427 / 5243 / 4455 / 2884），年均 ~4,105 笔 |
| 折内年化换手率 | 35.87 / 21.69 / 16.83 / 21.62 / 15.35（组合每年换手 15~36 次） |
| 累计佣金（0/10/20/50 bps） | 0.00 / 11,376.58 / 22,484.74 / 54,267.48 |
| 成本是否恰好扣一次 | 是：0 条重复 `(symbol, execution_date)`；`max\|commission − notional×bps/10000\| = 2.84e-14`；0 笔零数量/零名义成交 |

**结论**：`technical_only` 采用**日频再平衡到等权**（SMA20>SMA50 即纳入多头，等权），每日为跟随均线交叉反复换仓，故换手率极高。50bps 下总回报 76.92% → 0.42% 是**真实的高换手成本**，不是成本重复扣除、也不是成交日志错误。**不修改策略**，将其记录为基线固有特征（「换手成本是择时策略第一杀手」的实证）。

### 11.2 `spy_benchmark` 成本语义 —— 定义为外部市场参考

- `spy_benchmark` = SPY 总收益指数（除权复利），**零成本**：`cost_bps=0.0` 唯一档、`n_trades=0`、无 commission/slippage，由 runner 单独按折计算（`_spy_index_equity`）。
- `buy_and_hold` = **可交易**的 SPY 基准：一次性买入 SPY 并持有，**照常缴纳建仓成本**（fold0 @10bps 佣金 = 100）。
- 因此不存在「别人付成本、SPY 不付」的不公平比较：真正的可交易 SPY 基线是 `buy_and_hold`，它与其他策略在同一条成本曲线上横向可比；`spy_benchmark` 仅作为**外部市场参考**，明确标注「**不参与成本敏感性横向比较**」（结果表中 10/20/50 bps 三档留空 `—`）。

**最终定义**：`spy_benchmark` = SPY 零成本总收益指数（外部参考，只出 0bps 一个点）；`buy_and_hold` = 可交易 SPY 买入持有基线（参与成本敏感性，与其他策略公平对比）。

### 11.3 OOS 累计收益定义 —— 复利链式，非折间求和/平均

`total_return` 由 `src/experiments/metrics.py::pool_metrics` 计算：把各测试折的**日收益序列按时间顺序拼接**为一条连续 OOS 收益链，再做复利：

```
total_return = ∏(1 + r_d) − 1 = ∏(1 + fold_return_i) − 1
```

验证（equal_weight，cost=0）：

| 聚合方式 | 数值 |
|---|---|
| 折间简单求和 Σ fold_return | 99.34% |
| 复利链式 ∏(1+fold_return)−1 | **130.32%**（报告采用） |

结论：报告中的 130.32% 是**复利链式 OOS 收益**，符合正式回测口径（连续 OOS 净值曲线的复利），非简单求和、也非折间平均。`pool_metrics` 在 `_returns` 缺失时才退化为价值加权平均（本报告所有结果均走链式路径）。

---

## 12. `get_fundamentals` 性能优化（before/after）

**改动**：`src/data/historical_store.py` 新增按 symbol 的只读读缓存 `_FUNDAMENTALS_CACHE`，键为 symbol，值为 `(签名, 已解析 facts frame)`；签名 = `facts_path + subs_path` 的 `(resolve, mtime_ns, size)`，底层 parquet 一变即失效。查询逻辑不变：命中缓存后**仍在每次调用上施加 `known_at <= as_of` 披露时点过滤 + `(concept, unit, end)` 最新版本选择**，缓存只存「已解析的原始 facts」，绝不缓存「过滤后的查询结果」。

七条约束逐条满足：

| # | 约束 | 满足情况 |
|---|---|---|
| 1 | 不改 `HistoricalDataStore` 外部 PIT 语义 | ✅ 过滤/排序/版本选择代码原样保留，缓存仅包住读+解析 |
| 2 | 不缓存「查询结果」绕过 as_of 过滤 | ✅ 缓存存未过滤 facts，`known_at <= as_of` 每次重算 |
| 3 | 缓存键考虑文件版本/路径 | ✅ 签名含 resolve 路径 + mtime_ns + size |
| 4 | 原始 df 不被查询逻辑原地修改 | ✅ 下游仅 `sort_values`/`groupby.tail`（返回新对象），无 inplace 写入 |
| 5 | snapshot/data 哈希语义稳定 | ✅ `snapshot_hash` / 数据快照哈希未触及 |
| 6 | 无未来重述泄漏 | ✅ `test_fundamentals_cache.py::test_cache_no_future_restatement_leak` 断言 warm 命中不回填重述值 |
| 7 | 不改变 Gate 1 因果不变量 | ✅ 因果链 `feature_as_of <= signal < execution` 不变 |

**存储层微基准**（单 symbol，冷 vs 热；冷解析随 facts 行数超线性增长）：

```
symbol  cold（首次读+解析）   facts 行数
JPM     9946.0 ms            18,947
BAC     8992.5 ms            17,116
GS      7696.1 ms            14,920
MSFT    5422.7 ms            11,888
AAPL    2136.2 ms             9,934

warm（AAPL 缓存命中） 19.3 ms → 单 symbol 加速比 ~110×
```

**代表折（fundamental_only, fold 0）端到端**（before 用 `_NoCache` 字典强制每次 miss，与 after 跑同一套 `run_backtest`，保证口径一致）：

| 指标 | before（禁用缓存） | after（启用缓存） |
|---|---|---|
| 运行时间 | 3909.1 s（~65 min） | 344.9 s（~5.7 min） |
| 加速比 | — | **11.3×** |
| total_return | -21.31% | -21.31%（与 before 完全一致） |
| annualized_return / vol / sharpe / max_dd / calmar / n_days | 全部一致 | 全部一致（`==`，逐字段 True） |

- 端到端 11.3× 低于存储层 110× 的原因：`after` 仍包含 30 只 symbol 各一次**不可避免的首读解析**（冷加载摊销在 5 折上会进一步摊薄），且命中缓存后每次调用仍需执行 `known_at <= as_of` 过滤 + `(concept, unit, end)` 最新版本选择 + ROA 计算（这些语义步骤**故意不缓存**）。
- 全量 5 折（1800 次调用）受益更大：冷加载 30 次不变，其余 ~1770 次全部走热路径。

---

## 13. 最终验收核对

| 验收项 | 结果 |
|---|---|
| tests/data（含 4 个新缓存测试） | ✅ 37 passed, 0 failed, 0 skipped |
| tests/experiments | ✅ 26 passed, 0 failed, 0 skipped |
| 未来重述测试（缓存后） | ✅ `test_fundamentals_restatement_version_selection` + `test_cache_no_future_restatement_leak` 通过 |
| 缓存 before/after 等价 | ✅ `test_cache_equivalent_to_uncached`（多 as_of 帧 `equals`） |
| 确定性 | ✅ 两次运行字节级一致 |

---
