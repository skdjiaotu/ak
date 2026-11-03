"""科创50 位置危险度评估 —— 主入口。

用法：
    python -m star_risk.run

输出：科创50(000688) 当前危险度评估报告（估值分位 / 技术结构 / 情绪资金 / 综合判定）。
"""

from __future__ import annotations

from gem_risk.engine import assess_gem
from star_risk.fetcher import build_star50_dataset, FetchError


def _fmt_pct(v) -> str:
    if v is None:
        return "N/A"
    return f"{v:.2%}"


def _fmt_num(v, digits=2) -> str:
    if v is None:
        return "N/A"
    return f"{v:.{digits}f}"


def print_report(result: dict, ds: dict):
    W = 86
    val = result["valuation"]
    tech = result["technical"]
    sent = result["sentiment"]
    cur = ds["current"]
    extra = ds.get("extra", {})

    print("=" * W)
    print("科创50 位置危险度评估报告")
    print(f"数据时间: {ds['fetched_at']}    指数: 科创50(000688)")
    print("=" * W)

    # 当前行情与估值
    print("\n【0】当前估值（蛋卷基金，完整历史分位）")
    print(f"  PE-TTM:             {_fmt_num(cur.get('pe_ttm'))} 倍")
    print(f"  PE 历史分位:        {_fmt_pct(val.get('pe_percentile'))}")
    print(f"  PB:                 {_fmt_num(cur.get('pb'))} 倍")
    print(f"  PB 历史分位:        {_fmt_pct(val.get('pb_percentile'))}")
    print(f"  ROE:                {_fmt_pct(extra.get('roe'))}")
    print(f"  股息率:             {_fmt_pct(extra.get('dividend_yield'))}")
    if extra.get("eva_type"):
        print(f"  蛋卷估值评级:       {extra['eva_type']}")

    # 维度2：技术结构
    print("\n【1】技术结构")
    print(f"  最新收盘:           {_fmt_num(tech.get('close'), 2)}")
    print(f"  MA20 / MA60 / MA120 / MA250:  "
          f"{_fmt_num(tech.get('ma20'),0)} / {_fmt_num(tech.get('ma60'),0)} / "
          f"{_fmt_num(tech.get('ma120'),0)} / {_fmt_num(tech.get('ma250'),0)}")
    print(f"  距 MA20 乖离:       {_fmt_pct(tech.get('bias_ma20'))}")
    print(f"  距 MA60 乖离:       {_fmt_pct(tech.get('bias_ma60'))}")
    print(f"  距 250 日高点回撤:  {_fmt_pct(tech.get('drawdown_from_high'))}"
          f"  （高点 {_fmt_num(tech.get('high_250'),0)}）")
    print(f"  年内涨跌幅:         {_fmt_pct(tech.get('ytd_return'))}")
    print(f"  近 20 日涨跌幅:     {_fmt_pct(tech.get('mom_20d'))}")

    # 维度3：情绪与量能
    print("\n【2】市场情绪与量能")
    print(f"  最新成交量:         {_fmt_num(sent.get('cur_volume')/1e8, 1)} 亿股")
    print(f"  量能比(20日均):     {_fmt_num(sent.get('vol_ratio_20'))} 倍")
    print(f"  量能比(60日均):     {_fmt_num(sent.get('vol_ratio_60'))} 倍")

    # 综合判定
    print("\n" + "-" * W)
    print(f"【综合判定】危险度评分: {result['composite_score']:.0f} / 100")
    print(f"           信号: {result['signal']}")
    print(f"           建议: {result['advice']}")
    print("-" * W)

    # 细分项打分
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

    # 提示
    if result["notes"]:
        print("\n【要点提示】")
        for n in result["notes"]:
            print(f"  {n}")

    print("\n" + "=" * W)
    print("⚠️  本评估仅基于公开数据与经验阈值的量化参考，不构成投资建议。")
    print("   估值分位低 ≠ 不会继续跌；请结合基本面、政策与资金面综合判断。")
    print("=" * W)


def main():
    print("正在采集科创50 数据（蛋卷基金 + 新浪财经 + 乐咕乐股）...")
    try:
        ds = build_star50_dataset()
    except FetchError as e:
        print(f"❌ 数据采集失败: {e}")
        print("提示：可能是网络或数据源临时不可用，请稍后重试。")
        return

    result = assess_gem(ds)
    print_report(result, ds)


if __name__ == "__main__":
    main()
