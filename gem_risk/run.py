"""创业板位置危险度评估 —— 主入口。

用法：
    python -m gem_risk.run

输出：创业板指当前危险度评估报告（估值分位 / 技术结构 / 情绪资金 / 综合判定）。
"""

from __future__ import annotations

from gem_risk.fetcher import build_gem_dataset, FetchError
from gem_risk.engine import assess_gem


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

    print("=" * W)
    print("创业板位置危险度评估报告")
    print(f"数据时间: {ds['fetched_at']}    指数: 创业板指(399006)")
    print("=" * W)

    # 当前行情
    print("\n【0】当前行情（国证指数官方）")
    print(f"  收盘点位:   {_fmt_num(cur.get('close'))}")
    print(f"  当日涨跌:   {_fmt_pct(cur.get('change_pct'))}")
    print(f"  成交额:     {_fmt_num(cur.get('turnover'), 0)} 亿元")
    print(f"  总市值:     {_fmt_num(cur.get('total_mv'), 0)} 亿元")

    # 维度1：估值分位
    print("\n【1】估值分位（危险度核心）")
    print(f"  PE-TTM:             {_fmt_num(val.get('pe_ttm'))} 倍")
    print(f"  PE 历史分位:        {_fmt_pct(val.get('pe_percentile'))}"
          f"   （基于创业板50 滚动PE序列 {val.get('pe_series_len')} 期）")
    print(f"  PB:                 {_fmt_num(val.get('pb_current'))} 倍")
    print(f"  PB 历史分位:        {_fmt_pct(val.get('pb_percentile'))}")
    if val.get("erp") is not None:
        erp = val["erp"]
        verdict = "股比债便宜" if erp > 0.02 else ("中性" if erp > 0 else "股比债贵")
        print(f"  股债性价比 ERP:     {_fmt_pct(erp)}  （1/PE - 10年国债2.5%，{verdict}）")
    print(f"  全市场 PE(参考):    {_fmt_num(val.get('market_pe'))} 倍")

    # 维度2：技术结构
    print("\n【2】技术结构")
    print(f"  MA20 / MA60 / MA120 / MA250:  "
          f"{_fmt_num(tech.get('ma20'),0)} / {_fmt_num(tech.get('ma60'),0)} / "
          f"{_fmt_num(tech.get('ma120'),0)} / {_fmt_num(tech.get('ma250'),0)}")
    print(f"  距 MA20 乖离:       {_fmt_pct(tech.get('bias_ma20'))}")
    print(f"  距 MA60 乖离:       {_fmt_pct(tech.get('bias_ma60'))}")
    print(f"  距 250 日高点回撤:  {_fmt_pct(tech.get('drawdown_from_high'))}"
          f"  （高点 {_fmt_num(tech.get('high_250'),0)}）")
    print(f"  年内涨跌幅:         {_fmt_pct(tech.get('ytd_return'))}")
    print(f"  近 20 日涨跌幅:     {_fmt_pct(tech.get('mom_20d'))}")

    # 维度3：情绪与资金
    print("\n【3】市场情绪与量能")
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
    print("正在采集创业板数据（国证指数 + 乐咕乐股 + 新浪财经）...")
    try:
        ds = build_gem_dataset()
    except FetchError as e:
        print(f"❌ 数据采集失败: {e}")
        print("提示：可能是网络或数据源临时不可用，请稍后重试。")
        return

    result = assess_gem(ds)
    print_report(result, ds)


if __name__ == "__main__":
    main()
