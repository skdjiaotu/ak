"""
DCF 估值模型 —— 主入口。

用法：
    python dcf/run_dcf.py                # 默认对贵州茅台(600519.SH)估值
    python dcf/run_dcf.py 000858.SZ      # 指定股票代码（五粮液）
    python dcf/run_dcf.py 00700.HK       # 港股（腾讯控股）

流程：
    抓取历史财务数据 → 推导驱动假设 → 投影 FCFF → WACC → 终值 →
    企业价值 → 股权价值 → 每股价值 → 敏感性分析 → 输出报告。
"""

from __future__ import annotations

import sys

from dcf.fetcher import build_financial_dataset, FetchError
from dcf.engine import (
    DCFAssumptions,
    calc_cost_of_equity,
    calc_wacc,
    run_dcf,
    sensitivity_matrix,
)


# ---------------------------------------------------------------------------
# 由历史数据推导假设（黑箱：公式而非硬编码）
# ---------------------------------------------------------------------------
def derive_assumptions(ds: dict, code: str) -> DCFAssumptions:
    """从历史财务数据推导 DCF 假设，确保假设有数据支撑、可追溯。"""
    income = ds["income"]
    cashflow = ds["cashflow"]
    balance = ds["balance"]

    if len(income) < 2:
        raise FetchError("历史财务数据不足，无法推导假设")

    # 基准营收 = 最近一年营收
    base_revenue = income[-1]["revenue"]

    # 营收复合增长率（CAGR，近 3 年）
    def _cagr(vals):
        if len(vals) < 2 or vals[0] <= 0:
            return 0.06
        return (vals[-1] / vals[0]) ** (1 / (len(vals) - 1)) - 1

    revs = [r["revenue"] for r in income[-4:]]
    hist_growth = _cagr(revs)
    # 增长率假设：历史增速向长期均值回落（避免外推高增长）
    g1 = max(0.03, min(hist_growth * 0.7, 0.18))
    growth = [g1, g1 * 0.85, g1 * 0.7, g1 * 0.55, g1 * 0.4]

    # 历史 EBIT 利润率近似：用 (净利润 + 所得税) / 营收，再取近年均值
    # 简化：净利率 + 有效税率回推经营利润率
    net_margin = income[-1]["net_margin"]
    tax_rate = income[-1]["tax_rate"]
    est_ebit_margin = net_margin / (1 - tax_rate)  # 近似：EBIT/Rev ≈ NI/(1-t)/Rev
    est_ebit_margin = max(0.10, min(est_ebit_margin, 0.85))
    ebit_margin = [est_ebit_margin] * 5

    # 资本开支 / 营收 与 折旧 / 营收（近 3 年均值）
    def _ratio(cf_field, key="revenue"):
        vals = []
        for i, cf in enumerate(cashflow):
            rev = next((r["revenue"] for r in income if r["report_date"] == cf["report_date"]), None)
            if rev and rev > 0:
                vals.append(cf[cf_field] / rev)
        return sum(vals[-3:]) / len(vals[-3:]) if vals else 0.0

    capex_pct = max(0.005, _ratio("capex"))
    dep_pct = max(0.005, _ratio("depreciation_amortization"))

    # 净营运资本 / 营收（近 1 年）
    if balance:
        b = balance[-1]
        nwc = b["current_assets"] - b["current_liabilities"]
        nwc_pct = max(0.0, nwc / base_revenue) if base_revenue > 0 else 0.20
    else:
        nwc_pct = 0.20

    a = DCFAssumptions(
        revenue_growth=growth,
        ebit_margin=ebit_margin,
        tax_rate=tax_rate if 0 < tax_rate < 1 else 0.25,
        capex_pct_revenue=[capex_pct] * 5,
        dep_pct_revenue=[dep_pct] * 5,
        nwc_pct_revenue=nwc_pct,
        tax_rate_wacc=tax_rate if 0 < tax_rate < 1 else 0.25,
    )
    return a, base_revenue


def _net_debt_and_weight(ds: dict):
    """计算净债务与债务权重。"""
    balance = ds["balance"]
    if balance:
        b = balance[-1]
        cash = b.get("cash", 0.0)
        debt = b.get("interest_bearing_debt", 0.0)
        net_debt = debt - cash
        equity = b.get("equity", 0.0)
        debt_weight = debt / (debt + equity) if (debt + equity) > 0 else 0.0
    else:
        net_debt, debt_weight = 0.0, 0.0
    return net_debt, debt_weight


# ---------------------------------------------------------------------------
# 报告输出
# ---------------------------------------------------------------------------
def _fmt_money(v: float) -> str:
    """金额格式化：亿元。"""
    if abs(v) >= 1e8:
        return f"{v / 1e8:,.1f} 亿"
    if abs(v) >= 1e4:
        return f"{v / 1e4:,.0f} 万"
    return f"{v:,.0f}"


def print_report(code: str, ds: dict, a: DCFAssumptions, base_revenue: float,
                 net_debt: float, total_shares: float, debt_weight: float):
    """打印估值报告。"""
    company = ds["company"]
    res = run_dcf(base_revenue, net_debt, total_shares, 0.0, a, debt_weight)

    W = 84
    print("=" * W)
    print(f"DCF 估值报告 —— {company.get('name', code)} ({code})")
    print(f"行业: {company.get('industry', 'N/A')}    总股本: {total_shares/1e8:,.2f} 亿股")
    print("=" * W)

    print("\n【1】关键历史数据（最近一年）")
    income = ds["income"][-1]
    print(f"  营业收入:        {_fmt_money(income['revenue'])}")
    print(f"  归母净利润:      {_fmt_money(income['net_profit'])}")
    print(f"  净利率:          {income['net_margin']:.2%}")
    print(f"  毛利率:          {income['gross_margin']:.2%}")
    print(f"  ROE:             {income['roe']:.2%}")
    print(f"  有效税率:        {income['tax_rate']:.2%}")

    print("\n【2】核心假设")
    print(f"  预测期:          {a.forecast_years} 年")
    print(f"  营收增速(逐年):  {', '.join(f'{g:.1%}' for g in a.revenue_growth)}")
    print(f"  EBIT 利润率:     {a.ebit_margin[0]:.1%}（逐年相同）")
    print(f"  无风险利率 Rf:   {a.risk_free_rate:.2%}")
    print(f"  股权风险溢价:    {a.equity_risk_premium:.2%}")
    print(f"  Beta:            {a.beta}")
    print(f"  债务成本 Kd:     {a.cost_of_debt:.2%}")
    print(f"  税率:            {a.tax_rate:.2%}")
    print(f"  永续增长率 g:    {a.terminal_growth_rate:.2%}")

    ke = res["cost_of_equity"]
    print(f"\n  股权成本 Ke:     {ke:.2%}  (CAPM: Rf + β×ERP)")
    print(f"  WACC:            {res['wacc']:.2%}")

    print("\n【3】FCFF 投影（亿元）")
    print(f"  {'年份':<6}{'营收':>12}{'EBIT':>12}{'NOPAT':>12}{'D&A':>10}{'Capex':>10}{'ΔNWC':>10}{'FCFF':>12}")
    for r in res["forecast"]:
        print(f"  Y{r.year:<5}"
              f"{r.revenue/1e8:>12,.1f}{r.ebit/1e8:>12,.1f}{r.nopat/1e8:>12,.1f}"
              f"{r.dep/1e8:>10,.1f}{r.capex/1e8:>10,.1f}{r.nwc_change/1e8:>10,.1f}"
              f"{r.fcff/1e8:>12,.1f}")

    print("\n【4】估值结果")
    print(f"  预测期 FCFF 现值:   {_fmt_money(res['pv_fcff'])}")
    print(f"  终值 TV:            {_fmt_money(res['terminal_value'])}")
    print(f"  终值现值:           {_fmt_money(res['pv_terminal_value'])}")
    print(f"  终值占比:           {res['tv_pct']:.1%}  {'（偏高，注意假设合理性）' if res['tv_pct'] > 0.70 else '（合理）'}")
    print(f"  ─────────────────────────────")
    print(f"  企业价值 EV:        {_fmt_money(res['enterprise_value'])}")
    print(f"  减: 净债务:         {_fmt_money(net_debt)}")
    print(f"  股权价值:           {_fmt_money(res['equity_value'])}")
    print(f"  每股价值:           ¥ {res['per_share']:,.2f}")

    # 敏感性分析
    wacc_range = [round(res['wacc'] - 0.02, 3), round(res['wacc'] - 0.01, 3),
                  round(res['wacc'], 3), round(res['wacc'] + 0.01, 3),
                  round(res['wacc'] + 0.02, 3)]
    g_range = [0.015, 0.02, 0.025, 0.03, 0.035]
    sens = sensitivity_matrix(base_revenue, net_debt, total_shares, 0.0, a,
                              wacc_range, g_range, debt_weight)

    print("\n【5】敏感性分析：每股价值 (¥)  [行=WACC, 列=永续增长率 g]")
    header = "   " + "".join(f"{g:>10.1%}" for g in g_range)
    print(header)
    for w in wacc_range:
        row = sens["matrix"][w]
        cells = "".join(f"{row[g]:>10.0f}" for g in g_range)
        print(f"  {w:>7.2%}{cells}")

    print("\n" + "=" * W)
    print("⚠️  本模型仅用于研究教学演示，不构成任何投资建议。")
    print("   关键假设（增长、利润率、WACC、永续增长率）需结合基本面审慎复核。")
    print("=" * W)


def main():
    code = sys.argv[1] if len(sys.argv) > 1 else "600519.SH"

    print(f"正在抓取 {code} 的历史财务数据...")
    ds = build_financial_dataset(code)
    company = ds["company"]

    # 股本：优先用抓到的总股本
    total_shares = company.get("total_shares", 0.0)
    if total_shares <= 0:
        # 回退：用 EPS 反推总股本
        income = ds["income"]
        if income:
            latest = income[-1]
            if latest.get("eps", 0) > 0 and latest.get("net_profit", 0) > 0:
                total_shares = latest["net_profit"] / latest["eps"]

    a, base_revenue = derive_assumptions(ds, code)
    net_debt, debt_weight = _net_debt_and_weight(ds)

    print_report(code, ds, a, base_revenue, net_debt, total_shares, debt_weight)


if __name__ == "__main__":
    main()
