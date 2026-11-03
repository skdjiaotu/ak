# strategy_log —— 每日策略数据台账

把各策略每天跑出的核心信号/指标统一写入本地 **SQLite**，供后台统一查看与趋势分析。

## 设计思路

项目里有多个每天跑一次的策略（情绪择时、创业板/科创板位置、市场体检等），
它们之前只打印终端 + 生成 HTML，**结果没有持久化**，无法跨天追溯。

本模块提供一个统一台账：各策略 `run.py` 里加一行 `record(...)`，
自动把引擎返回的结构化结果快照写入 SQLite。

## 数据表

单表 `runs`：

| 字段 | 说明 |
|------|------|
| strategy | 策略名（如 `gem_position`） |
| run_date | 运行日期 YYYY-MM-DD |
| run_at | 运行时间戳 |
| payload | JSON 快照（完整指标字典） |

存储位置：`strategy_log/data.db`

## 接入方式

在策略 `run.py` 末尾加：

```python
from strategy_log import record
record("策略名", {
    "核心指标": 值,
    "信号": "...",
})
```

已接入的策略：

| 策略名 | 记录的核心指标 |
|--------|---------------|
| `gem_position`（创业板位置） | 位置温度、建议仓位、PE/PB 分位、价格分位、距高点回撤、信号 |
| `star_position`（科创板位置） | 同上 + ROE |
| `sentiment`（市场情绪） | 情绪热度、建议仓位、各因子分位 |
| `daily_report`（市场体检） | 综合判定、红/黄/绿灯数、指数、资金面、波动率 |

## 查询 API（集成在持仓后台）

- `GET /api/strategy/overview` — 台账概览 + 策略列表 + 最新信号
- `GET /api/strategy/{strategy}/history` — 某策略历史快照
- `GET /api/strategy/{strategy}/series?metric=xxx` — 某指标时间序列（点号路径，如 `position_temp`、`components.pe`）

后台页面：http://127.0.0.1:8765/strategy

## 说明

- 记录失败不影响策略主流程（try/except 包裹，仅打印警告）。
- `payload` 支持任意嵌套结构，numpy 标量自动转 Python 原生类型。
- 指标序列用点号路径提取嵌套值，便于画趋势图。
