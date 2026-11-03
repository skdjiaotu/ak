"""
DCF 估值计算引擎 —— 投行级 FCFF 自由现金流折现模型。

模型结构（自上而下）：
    1. 历史财务数据 → 推导驱动假设（增长率、利润率、资本密集度）
    2. 假设区 → 显式预测 5 年 FCFF
    3. WACC = E/(E+D) * CostOfEquity + D/(E+D) * CostOfDebt * (1 - tax)
        CostOfEquity = Rf + β * ERP  （CAPM）
    4. 终值 TV = FCFF_T * (1+g) / (WACC - g)   （Gordon 永续增长法）
    5. 企业价值 EV = Σ PV(FCFF) + PV(TV)
    6. 股权价值 = EV - 净债务 + 非经营性资产
    7. 每股价值 = 股权价值 / 总股本

所有假设独立存放于 DCFAssumptions，计算全程用引用，无硬编码，
符合投行建模规范（蓝=输入 / 黑=公式 / 绿=跨表引用）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


# ---------------------------------------------------------------------------
# 假设区（蓝色输入 —— 用户可改）
# ---------------------------------------------------------------------------
@dataclass
class DCFAssumptions:
    """DCF 关键假设。所有字段均可由用户覆盖。"""

    # --- 预测期 ---
    forecast_years: int = 5            # 显式预测期年数

    # --- 营收增长假设 ---
    revenue_growth: List[float] = field(default_factory=lambda: [0.10, 0.10, 0.08, 0.08, 0.06])

    # --- 利润率假设 ---
    ebit_margin: List[float] = field(default_factory=lambda: [0.68, 0.68, 0.68, 0.68, 0.68])

    # --- 税率 ---
    tax_rate: float = 0.25

    # --- 再投资假设（占营收比例） ---
    capex_pct_revenue: List[float] = field(default_factory=lambda: [0.03, 0.03, 0.03, 0.03, 0.03])
    dep_pct_revenue: List[float] = field(default_factory=lambda: [0.012, 0.012, 0.012, 0.012, 0.012])
    nwc_pct_revenue: float = 0.40      # 净营运资本占营收比例（用于计算变动）

    # --- WACC 分量 ---
    risk_free_rate: float = 0.025      # 无风险利率（10 年期国债）
    equity_risk_premium: float = 0.06  # 股权风险溢价 ERP
    beta: float = 1.0                  # 贝塔
    cost_of_debt: float = 0.04         # 税前债务成本
    tax_rate_wacc: float = 0.25        # 计算税盾用的税率（可与上面相同）

    # --- 资本结构 ---
    # 目标股权权重（1 - debt_weight）；若为 None 则用公司实际净债务比例估算
    target_debt_weight: Optional[float] = None

    # --- 终值 ---
    terminal_growth_rate: float = 0.03  # 永续增长率 g（不得超过长期 GDP 增速，通常 2~3%）

    # --- 市值调整项 ---
    # 净债务 = 有息负债 - 货币资金；非经营性资产（如长期股权投资）默认 0
    non_operating_assets: float = 0.0

    def _validate(self) -> None:
        """假设合理性校验：越界直接抛错，避免"反推结论"。"""
        if self.forecast_years < 3:
            raise ValueError("预测期至少 3 年")
        if self.forecast_years != len(self.revenue_growth):
            raise ValueError("revenue_growth 长度必须等于 forecast_years")
        if self.terminal_growth_rate >= min(self.risk_free_rate + self.equity_risk_premium, 0.05):
            raise ValueError(
                f"永续增长率 {self.terminal_growth_rate:.2%} 过高，"
                f"应显著低于 WACC 且不超过长期名义 GDP 增速（通常 2~3%）"
            )
        if self.terminal_growth_rate < 0:
            raise ValueError("永续增长率不应为负")
        if not 0 < self.tax_rate < 1:
            raise ValueError("税率应在 (0,1) 区间")
        if self.beta <= 0:
            raise ValueError("beta 应大于 0")


# ---------------------------------------------------------------------------
# WACC 计算
# ---------------------------------------------------------------------------
def calc_cost_of_equity(a: DCFAssumptions) -> float:
    """CAPM 股权成本：Ke = Rf + β * ERP。"""
    return a.risk_free_rate + a.beta * a.equity_risk_premium


def calc_wacc(a: DCFAssumptions, debt_weight: Optional[float] = None) -> float:
    """加权平均资本成本。

    若 target_debt_weight 未指定，则使用传入 debt_weight（来自公司实际
    净债务比例）；否则用假设区目标值。
    """
    ke = calc_cost_of_equity(a)
    kd = a.cost_of_debt
    t = a.tax_rate_wacc

    if a.target_debt_weight is not None:
        wd = a.target_debt_weight
    else:
        wd = debt_weight if debt_weight is not None else 0.0
    wd = max(0.0, min(wd, 0.9))  # 夹在 [0, 0.9]
    we = 1.0 - wd

    return we * ke + wd * kd * (1 - t)


# ---------------------------------------------------------------------------
# FCFF 投影
# ---------------------------------------------------------------------------
@dataclass
class ForecastRow:
    """单年 FCFF 预测明细。"""
    year: int
    revenue: float
    ebit: float
    nopat: float
    dep: float
    capex: float
    nwc_change: float
    fcff: float


def project_fcff(base_revenue: float, a: DCFAssumptions) -> List[ForecastRow]:
    """基于基准年营收，投影预测期 FCFF。

    FCFF = EBIT * (1 - t) + D&A - Capex - ΔNWC
    """
    rows: List[ForecastRow] = []
    revenue = base_revenue
    prev_nwc = base_revenue * a.nwc_pct_revenue  # 基期营运资本

    for i in range(a.forecast_years):
        growth = a.revenue_growth[i]
        margin = a.ebit_margin[i]
        capex_pct = a.capex_pct_revenue[i]
        dep_pct = a.dep_pct_revenue[i]

        revenue = revenue * (1 + growth)
        ebit = revenue * margin
        nopat = ebit * (1 - a.tax_rate)
        dep = revenue * dep_pct
        capex = revenue * capex_pct
        nwc = revenue * a.nwc_pct_revenue
        nwc_change = nwc - prev_nwc
        prev_nwc = nwc

        fcff = nopat + dep - capex - nwc_change
        rows.append(ForecastRow(
            year=i + 1,
            revenue=revenue,
            ebit=ebit,
            nopat=nopat,
            dep=dep,
            capex=capex,
            nwc_change=nwc_change,
            fcff=fcff,
        ))
    return rows


# ---------------------------------------------------------------------------
# 折现与估值
# ---------------------------------------------------------------------------
def _discount(rows: List[ForecastRow], wacc: float, tgr: float) -> dict:
    """折现预测期 FCFF + 终值，返回企业价值与明细。"""
    pv_fcff_sum = 0.0
    pv_details = []
    for i, r in enumerate(rows):
        df = 1.0 / (1 + wacc) ** (i + 1)
        pv = r.fcff * df
        pv_fcff_sum += pv
        pv_details.append({"year": r.year, "fcff": r.fcff, "df": df, "pv": pv})

    # 终值：Gordon 永续增长
    last_fcff = rows[-1].fcff
    tv = last_fcff * (1 + tgr) / (wacc - tgr)
    pv_tv = tv / (1 + wacc) ** len(rows)

    enterprise_value = pv_fcff_sum + pv_tv
    return {
        "pv_fcff": pv_fcff_sum,
        "terminal_value": tv,
        "pv_terminal_value": pv_tv,
        "enterprise_value": enterprise_value,
        "pv_details": pv_details,
        "tv_pct": pv_tv / enterprise_value,  # 终值占 EV 比重（健康应 < 70%）
    }


def run_dcf(
    base_revenue: float,
    net_debt: float,
    total_shares: float,
    non_operating_assets: float,
    a: DCFAssumptions,
    debt_weight: Optional[float] = None,
) -> dict:
    """执行完整 DCF 估值，返回结构化结果字典。"""
    a._validate()

    wacc = calc_wacc(a, debt_weight)
    ke = calc_cost_of_equity(a)
    rows = project_fcff(base_revenue, a)
    disc = _discount(rows, wacc, a.terminal_growth_rate)

    ev = disc["enterprise_value"]
    equity_value = ev - net_debt + non_operating_assets
    per_share = equity_value / total_shares if total_shares else 0.0

    return {
        "wacc": wacc,
        "cost_of_equity": ke,
        "forecast": rows,
        "pv_fcff": disc["pv_fcff"],
        "terminal_value": disc["terminal_value"],
        "pv_terminal_value": disc["pv_terminal_value"],
        "tv_pct": disc["tv_pct"],
        "enterprise_value": ev,
        "net_debt": net_debt,
        "equity_value": equity_value,
        "per_share": per_share,
        "pv_details": disc["pv_details"],
    }


# ---------------------------------------------------------------------------
# 敏感性分析
# ---------------------------------------------------------------------------
def sensitivity_matrix(
    base_revenue: float,
    net_debt: float,
    total_shares: float,
    non_operating_assets: float,
    a: DCFAssumptions,
    wacc_range: List[float],
    growth_range: List[float],
    debt_weight: Optional[float] = None,
) -> dict:
    """WACC × 永续增长率 双变量敏感性表，返回每股价值矩阵。"""
    matrix = {}
    for w in wacc_range:
        row = {}
        for g in growth_range:
            aa = DCFAssumptions(**{**a.__dict__.copy()})
            aa.terminal_growth_rate = g
            # 用指定 WACC 重新计算（直接覆盖折现率）
            res = _run_with_fixed_wacc(base_revenue, net_debt, total_shares,
                                       non_operating_assets, aa, w)
            row[g] = res["per_share"]
        matrix[w] = row
    return {
        "wacc_range": wacc_range,
        "growth_range": growth_range,
        "matrix": matrix,
    }


def _run_with_fixed_wacc(base_revenue, net_debt, total_shares,
                         non_op_assets, a: DCFAssumptions, fixed_wacc: float) -> dict:
    """固定 WACC 跑一遍 DCF（用于敏感性分析）。"""
    a._validate()
    rows = project_fcff(base_revenue, a)
    disc = _discount(rows, fixed_wacc, a.terminal_growth_rate)
    ev = disc["enterprise_value"]
    equity = ev - net_debt + non_op_assets
    per_share = equity / total_shares if total_shares else 0.0
    return {"enterprise_value": ev, "equity_value": equity, "per_share": per_share}
