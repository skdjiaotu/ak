"""A 股宽基指数危险度评估 —— 通用入口与对比看板。

用法：
    python -m index_risk.run                 # 输出所有指数危险度对比看板
    python -m index_risk.run 399001          # 单看深证成指
    python -m index_risk.run 399006 000688   # 指定多个指数

输出：各指数估值分位 / 技术结构 / 危险度评分 / 红黄绿灯对比。
"""

from __future__ import annotations

import sys

from gem_risk.engine import assess_gem
from index_risk.fetcher import (
    INDEX_CONFIG,
    build_index_dataset,
    FetchError,
)


def _fmt_pct(v) -> str:
    return "N/A" if v is None else f"{v:.2%}"


def _fmt_num(v, digits=2) -> str:
    return "N/A" if v is None else f"{v:.{digits}f}"


def _signal_color(signal: str) -> str:
    if "红" in signal:
        return "🔴"
    if "黄" in signal:
        return "🟡"
    return "🟢"


def assess_one(code: str):
    """评估单个指数，返回 (dataset, result)。"""
    ds = build_index_dataset(code)
    result = assess_gem(ds)
    return ds, result


def print_comparison(results: list):
    """打印多指数对比看板。"""
    W = 96
    print("=" * W)
    print("A 股宽基指数危险度对比看板")
    print(f"数据时间: {results[0][0]['fetched_at']}")
    print("=" * W)

    # 表头
    hdr = (f"{'指数':<10}{'PE':>8}{'PE分位':>9}{'PB':>8}{'PB分位':>9}"
           f"{'ROE':>8}{'回撤':>9}{'年内':>8}{'危险度':>8}  信号")
    print(hdr)
    print("-" * W)

    for ds, result in results:
        val = result["valuation"]
        tech = result["technical"]
        name = ds["index_name"]
        pe = _fmt_num(val.get("pe_ttm"), 1)
        pe_p = _fmt_pct(val.get("pe_percentile"))
        pb = _fmt_num(val.get("pb_current"), 2)
        pb_p = _fmt_pct(val.get("pb_percentile"))
        roe = _fmt_pct(ds.get("extra", {}).get("roe"))
        dd = _fmt_pct(tech.get("drawdown_from_high"))
        ytd = _fmt_pct(tech.get("ytd_return"))
        score = result["composite_score"]
        sig = result["signal"]
        print(f"{name:<10}{pe:>8}{pe_p:>9}{pb:>8}{pb_p:>9}"
              f"{roe:>8}{dd:>9}{ytd:>8}{score:>7.0f}  {sig}")

    print("-" * W)
    print("说明：PE/PB 分位来自蛋卷基金完整历史；回撤为距 250 日高点；")
    print("      危险度 0=安全 100=危险，越低越安全。")
    print("=" * W)


def print_single(ds, result):
    """打印单个指数详细报告。"""
    W = 86
    val = result["valuation"]
    tech = result["technical"]
    sent = result["sentiment"]
    extra = ds.get("extra", {})

    print("=" * W)
    print(f"{ds['index_name']} ({ds['index_code']}) 位置危险度评估")
    print(f"数据时间: {ds['fetched_at']}")
    print("=" * W)

    print("\n【1】估值分位（蛋卷基金，完整历史）")
    print(f"  PE-TTM:             {_fmt_num(val.get('pe_ttm'))} 倍")
    print(f"  PE 历史分位:        {_fmt_pct(val.get('pe_percentile'))}")
    print(f"  PB:                 {_fmt_num(val.get('pb_current'))} 倍")
    print(f"  PB 历史分位:        {_fmt_pct(val.get('pb_percentile'))}")
    print(f"  ROE:                {_fmt_pct(extra.get('roe'))}")
    print(f"  股息率:             {_fmt_pct(extra.get('dividend_yield'))}")
    if extra.get("eva_type"):
        print(f"  蛋卷估值评级:       {extra['eva_type']}")

    print("\n【2】技术结构")
    print(f"  最新收盘:           {_fmt_num(tech.get('close'), 2)}")
    print(f"  MA20 / MA60 / MA120 / MA250:  "
          f"{_fmt_num(tech.get('ma20'),0)} / {_fmt_num(tech.get('ma60'),0)} / "
          f"{_fmt_num(tech.get('ma120'),0)} / {_fmt_num(tech.get('ma250'),0)}")
    print(f"  距 MA20 乖离:       {_fmt_pct(tech.get('bias_ma20'))}")
    print(f"  距 250 日高点回撤:  {_fmt_pct(tech.get('drawdown_from_high'))}"
          f"  （高点 {_fmt_num(tech.get('high_250'),0)}）")
    print(f"  年内涨跌幅:         {_fmt_pct(tech.get('ytd_return'))}")
    print(f"  近 20 日涨跌幅:     {_fmt_pct(tech.get('mom_20d'))}")

    print("\n【3】市场情绪与量能")
    print(f"  量能比(20日均):     {_fmt_num(sent.get('vol_ratio_20'))} 倍")
    print(f"  量能比(60日均):     {_fmt_num(sent.get('vol_ratio_60'))} 倍")

    print("\n" + "-" * W)
    print(f"【综合判定】危险度评分: {result['composite_score']:.0f} / 100")
    print(f"           信号: {result['signal']}")
    print(f"           建议: {result['advice']}")
    print("-" * W)

    print("\n【指标打分明细】（0=安全，100=危险）")
    labels = {
        "pe_percentile": "PE 分位",
        "pb_percentile": "PB 分位",
        "bias": "均线乖离",
        "drawdown": "距前高回撤",
        "ytd": "年内涨幅",
        "volume": "量能",
    }
    for k, label in labels.items():
        if k in result["scores"]:
            bar = "█" * int(result["scores"][k] / 5)
            print(f"  {label:<12} {result['scores'][k]:>5.0f}  {bar}")

    if result["notes"]:
        print("\n【要点提示】")
        for n in result["notes"]:
            print(f"  {n}")

    print("\n" + "=" * W)
    print("⚠️  本评估仅基于公开数据与经验阈值的量化参考，不构成投资建议。")
    print("=" * W)


def main():
    args = sys.argv[1:]
    if not args:
        # 默认全部指数对比
        codes = list(INDEX_CONFIG.keys())
    else:
        codes = [c for c in args if c in INDEX_CONFIG]
        if not codes:
            print(f"未识别的指数代码，可选: {list(INDEX_CONFIG.keys())}")
            return

    print("正在采集数据（蛋卷基金 + 新浪财经 + 乐咕乐股）...")
    results = []
    for code in codes:
        try:
            ds, result = assess_one(code)
            results.append((ds, result))
        except FetchError as e:
            print(f"  ⚠️ {INDEX_CONFIG[code]['name']} 采集失败: {e}")

    if not results:
        print("❌ 所有指数采集失败，请检查网络后重试。")
        return

    if len(results) == 1:
        print_single(results[0][0], results[0][1])
    else:
        print_comparison(results)


if __name__ == "__main__":
    main()
