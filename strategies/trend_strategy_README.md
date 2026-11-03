# AKQuant 趋势交易策略（完整版）

基于 [AKQuant](https://akquant.akfamily.xyz/)（Rust 内核 + Python 接口）实现的趋势跟踪策略体系，含止损止盈、参数网格优化、多标的组合回测。

## 文件结构

```
trend_strategies.py   策略库（可导入模块：策略类 + 数据 + 绩效工具）
trend_strategy.py     单标的回测入口（含止损止盈增强对比）
trend_optimize.py     参数网格优化入口（多进程 Grid Search）
trend_portfolio.py    多标的组合回测入口
```

> 策略类放在可导入模块 `trend_strategies.py`，是因为 Windows 下网格优化多进程用 spawn 启动，要求策略类可导入、入口脚本有 `if __name__ == "__main__"` 保护。

## 四类策略

| 策略类 | 逻辑 |
|---|---|
| `DualMACrossStrategy` | 双均线金叉买入/死叉清仓 |
| `MA60TrendStrategy` | 站上 MA60 持有 / 跌破清仓 |
| `MA60WithStopStrategy` | MA60 + 固定比例止损止盈 |
| `MA60TrailingStopStrategy` | MA60 + 追踪止损 |

## 使用方法

```bash
# 1. 单标的回测（含止损止盈对比）
.venv/Scripts/python.exe trend_strategy.py --symbol 399006

# 2. 参数网格优化（多进程）
.venv/Scripts/python.exe trend_optimize.py --symbol 399006 --workers 4

# 3. 多标的组合回测
.venv/Scripts/python.exe trend_portfolio.py --strategy stop
.venv/Scripts/python.exe trend_portfolio.py --symbols 000300,399006
```

## 回测结论（2018-01 ~ 2026-10）

### 1. 止损止盈增强（创业板指）
| 策略 | 累计收益 | 最大回撤 | 夏普 |
|---|---|---|---|
| 买入持有 | +36.4% | -57.1% | — |
| MA60 基础 | +20.0% | -7.0% | 0.446 |
| MA60 + 止损止盈 | +21.8% | -7.1% | 0.488 |
| MA60 + 追踪止损 | +21.3% | -7.0% | 0.473 |

### 2. 参数网格优化（创业板指，112 组）
最优组合 `MA50 + 止损5% + 止盈20%` → 收益 26.8%、回撤 8.0%、夏普 0.595。
TOP15 参数收益集中在 23%~27%，说明参数空间稳健，非单点过拟合。

### 3. 多标的组合（六大宽基指数，MA60+止损止盈）
| 指标 | 组合策略 | 等权持有 |
|---|---|---|
| 累计收益 | +9.5% | +4.8% |
| 最大回撤 | -18.0% | -47.0% |

**单标的归因**：沪深300 +17.7万、创业板 +16.6万盈利；**中证500 -27.7万巨亏**拖后腿。
→ 趋势策略更适合大盘/中盘稳健标的，对高波动小盘标的（中证500/科创50）效果差。

## 核心洞察
1. **趋势策略价值 = 控回撤**（回撤从 -47%~-57% 压到 -7%~-18%），而非赚更多。
2. **止损止盈是锦上添花**：小幅提升收益与夏普，MA60 本身已把回撤控得很好。
3. **参数空间稳健**：网格优化显示最优参数不唯一，避免过拟合陷阱。
4. **组合需筛标的**：趋势策略不是对所有标的普适，高波动小盘股效果差。

## 关键技术要点（AKQuant API）
- `run_backtest(strategy=类, data=df, symbols=..., initial_cash, commission_rate)`
- 均线用 `get_history(count, symbol, field="close")` 手动算（比 `self.I(SMA)` 在网格搜索/多进程下更稳定）
- 必须先 `self.set_history_depth(n)` 启用历史追踪
- `run_grid_search(strategy, param_grid, data, symbols=..., initial_cash=..., sort_by, result_filter, max_workers)`
  - `symbols`/`initial_cash` 须通过 kwargs 传入
  - `result_filter` 接收 **dict**（用 `metrics["key"]` 访问，不是 `getattr`）
  - 字段单位：`total_return_pct`/`max_drawdown_pct` 是百分数，`annualized_return` 是小数
- `result.metrics` 是 MetricsWrapper（属性访问，非 dict）

## 免责声明
本策略仅供量化研究教学演示，不构成投资建议。
