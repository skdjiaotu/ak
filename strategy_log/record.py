"""策略记录辅助 —— 定义各策略要记录哪些核心指标，并提供便捷记录函数。

各策略引擎返回的字典字段繁多，这里抽取出「后台分析最有价值」的核心指标，
统一记录到 strategy_log 台账。

用法（在策略 run.py 里）：
    from strategy_log.record import record_strategy
    record_strategy("gem_position", result_dict)

或直接：
    from strategy_log import record
    record("gem_position", result_dict)
"""

from __future__ import annotations

from strategy_log import record

# 策略中文名（后台展示用）
STRATEGY_CN = {
    "gem_position": "创业板位置",
    "star_position": "科创板位置",
    "sentiment": "市场情绪",
    "daily_report": "市场体检",
    "timing": "市场择时",
    "fund_flow": "资金面",
    "portfolio": "我的持仓",
}

# 各策略的核心指标（后台趋势图 + 概览卡展示的字段）
# 值：{中文名: 点号路径}
CORE_METRICS = {
    "gem_position": {
        "位置温度": "position_temp",
        "建议仓位": "suggest_pos",
        "PE分位": "pe_pct",
        "价格分位(5年)": "price_pct_5y",
        "信号": "signal",
    },
    "star_position": {
        "位置温度": "position_temp",
        "建议仓位": "suggest_pos",
        "PE分位": "pe_pct",
        "价格分位(3年)": "price_pct_3y",
        "信号": "signal",
    },
    "sentiment": {
        "情绪热度": "heat",
        "建议仓位": "position",
        "信号": "signal",
    },
    "daily_report": {
        "综合判定": "overall",
        "红灯数": "red",
        "绿灯数": "green",
    },
}


def record_strategy(strategy: str, data: dict, run_date: str | None = None) -> int:
    """记录一次策略运行结果（等价于 strategy_log.record）。"""
    return record(strategy, data, run_date)


def cn(strategy: str) -> str:
    return STRATEGY_CN.get(strategy, strategy)
