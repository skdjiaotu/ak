# A 股宽基指数危险度评估（统一模块）

用一张配置表驱动，评估任意 A 股宽基指数的位置危险度，支持单指数详报与多指数对比看板。

> ⚠️ 仅基于公开数据与经验阈值的量化参考，**不构成投资建议**。

## 快速开始

```bash
.venv/Scripts/python.exe -m pip install akshare requests

# 1. 全部指数对比看板（6 个宽基指数）
.venv/Scripts/python.exe -m index_risk.run

# 2. 单个指数详细报告
.venv/Scripts/python.exe -m index_risk.run 399001      # 深证成指
.venv/Scripts/python.exe -m index_risk.run 399006      # 创业板指

# 3. 指定多个指数对比
.venv/Scripts/python.exe -m index_risk.run 399001 000688
```

## 支持的指数（新增只需在 fetcher.py 的 INDEX_CONFIG 加一行）

| 代码 | 名称 | 代码 | 名称 |
|------|------|------|------|
| 399006 | 创业板指 | 000300 | 沪深300 |
| 000688 | 科创50 | 000016 | 上证50 |
| 399001 | 深证成指 | 000905 | 中证500 |

## 数据源

- **蛋卷基金**（danjuanfunds.com）：指数当前 PE/PB + 完整历史分位（权威，一次拉取全部指数）
- **新浪财经**：指数历史日 K（均线、回撤、量能）
- **乐咕乐股**：全市场 PE（资金面温度）

## 架构说明

本模块是 `gem_risk`（创业板）、`star_risk`（科创50）的**通用化重构**：

- `fetcher.py`：蛋卷估值 + 新浪 K 线抽成通用函数，指数配置表驱动
- `run.py`：单指数详报 + 多指数对比看板
- 评分引擎复用 `gem_risk.engine.assess_gem`（估值分位 / 技术结构 / 情绪量能四维）

之前的 `gem_risk`、`star_risk` 包仍可独立运行，`index_risk` 是其统一入口。
