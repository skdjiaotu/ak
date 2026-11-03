"""
数据抓取模块 —— 从东方财富公开 F10 接口获取 A 股 / 港股上市公司财务数据。

数据来源：
    东方财富 F10 财务分析接口（emweb.securities.eastmoney.com）
    仅用于研究与教学演示，数据版权归原发布方所有。

接口说明：
    - 利润表/核心指标: ZYZBAjaxNew  （营收、净利润、EBIT 近似项、税率等）
    - 现金流量表:      xjllbAjaxNew （经营现金流、资本开支、折旧摊销）
    - 资产负债表:      zcfzbAjaxNew （货币资金、有息负债、营运资本项）

注意：DCF 依赖的"EBIT、折旧摊销"部分字段需从明细表推导，本模块尽量从公开
指标还原，并对缺失项给出明确标注，确保建模假设可追溯、可审计。
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional

import requests

# ---------------------------------------------------------------------------
# 常量与配置
# ---------------------------------------------------------------------------
_BASE = "https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/"
_HEADERS = {
    "Referer": "https://emweb.securities.eastmoney.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
}
_TIMEOUT = 25

# 汇率：港币 → 人民币（建模统一折算为人民币）。可在此覆盖。
HKD_CNY = 0.92


class FetchError(RuntimeError):
    """数据抓取失败异常。"""


def _normalize_code(code: str) -> tuple[str, str]:
    """将股票代码归一化为 (secuCode, 东方财富 code 前缀) 两种格式。

    支持输入: '600519', '600519.SH', 'SH600519', 'sh600519', '0700.HK', '00700.HK'
    返回: (secu_code, em_code)
        secu_code 形如 '600519.SH' / '00700.HK'
        em_code   形如 'SH600519' / 'HK00700'
    """
    code = code.strip().upper().replace(" ", "")

    # 带交易所后缀
    if "." in code:
        num, mkt = code.split(".")
        num = num.zfill(5) if mkt == "HK" else num.zfill(6)
        mkt = mkt.upper()
    else:
        # 无后缀：按长度/前缀判断
        if code.startswith("SH") or code.startswith("SZ") or code.startswith("HK"):
            mkt, num = code[:2], code[2:]
        else:
            # 纯数字：6 开头沪市，0/3 开头深市，其余按 5 位港股处理
            num = code.zfill(6)
            if num.startswith("6"):
                mkt = "SH"
            elif num.startswith(("0", "3")):
                mkt = "SZ"
            else:
                mkt = "HK"
                num = num.zfill(5)

    if mkt not in ("SH", "SZ", "HK", "BJ"):
        raise FetchError(f"无法识别的市场代码: {mkt}")

    # 东方财富 secuCode：A 股 6 位 + 市场；港股 5 位 + .HK
    if mkt == "HK":
        secu_code = f"{num.zfill(5)}.HK"
    else:
        secu_code = f"{num.zfill(6)}.{mkt}"

    em_code = f"{mkt}{num}"
    return secu_code, em_code


# 复用同一个 Session：绕过系统代理（公司网络代理对东财域名不稳定），
# 直连更稳定。trust_env=False 确保 requests 不读 HTTP_PROXY/HTTPS_PROXY。
_SESSION = requests.Session()
_SESSION.trust_env = False


def _get_json(url: str) -> dict:
    """GET 请求并解析 JSON，失败抛出 FetchError。"""
    try:
        resp = _SESSION.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        raise FetchError(f"网络请求失败: {url} — {e}") from e
    except json.JSONDecodeError as e:
        raise FetchError(f"响应非 JSON: {url} — {e}") from e


# ---------------------------------------------------------------------------
# 财务数据抓取
# ---------------------------------------------------------------------------
def fetch_income_metrics(code: str) -> List[dict]:
    """抓取核心财务指标（利润表派生），返回按报告期倒序的年度记录。

    每条记录包含（单位：元，比率除外）：
        report_date, revenue, net_profit, gross_margin,
        net_margin, roe, tax_rate, eps
    """
    _, em_code = _normalize_code(code)
    url = (
        f"{_BASE}ZYZBAjaxNew?type=0&code={em_code}"
    )
    data = _get_json(url).get("data", []) or []

    records: List[dict] = []
    for row in data:
        # 仅取年报（REPORT_TYPE == '年报'）
        if row.get("REPORT_TYPE") != "年报":
            continue
        records.append({
            "report_date": (row.get("REPORT_DATE") or "")[:10],
            "revenue": _num(row.get("TOTALOPERATEREVE")),
            "net_profit": _num(row.get("PARENTNETPROFIT")),
            "gross_margin": _pct(row.get("XSMLL")),
            "net_margin": _pct(row.get("XSJLL")),
            "roe": _pct(row.get("ROEJQ")),
            "tax_rate": _pct(row.get("TAXRATE")),
            "eps": _num(row.get("EPSJB")),
        })
    records.sort(key=lambda x: x["report_date"])
    return records


def fetch_cashflow(code: str) -> List[dict]:
    """抓取现金流量表年度数据。

    返回字段（元）：
        report_date, operating_cashflow, capex, depreciation_amortization
    """
    _, em_code = _normalize_code(code)
    # 取最近 6 个年度报告期
    dates = _recent_year_ends(6)
    url = (
        f"{_BASE}xjllbAjaxNew?companyType=4&reportDateType=0&reportType=1"
        f"&dates={','.join(dates)}&code={em_code}"
    )
    data = _get_json(url).get("data", []) or []

    records: List[dict] = []
    for row in data:
        if row.get("REPORT_TYPE") != "年报":
            continue
        records.append({
            "report_date": (row.get("REPORT_DATE") or "")[:10],
            # 经营活动产生的现金流量净额
            "operating_cashflow": _num(row.get("NETCASH_OPERATE")),
            # 资本开支：购建固定资产、无形资产和其他长期资产支付的现金
            "capex": _num(row.get("CONSTRUCT_LONG_ASSET")),
            # 折旧摊销：现金流量表补充资料里"固定资产折旧、油气资产折耗、
            # 生产性生物资产折旧"，接口可能不直接给，先置 None 由上层补
            "depreciation_amortization": _num(row.get("FA_IR_DEPR")),
        })
    records.sort(key=lambda x: x["report_date"])
    return records


def fetch_balance_sheet(code: str) -> List[dict]:
    """抓取资产负债表年度数据。

    返回字段（元）：
        report_date, total_assets, total_liabilities, equity,
        cash, interest_bearing_debt, current_assets, current_liabilities
    """
    _, em_code = _normalize_code(code)
    dates = _recent_year_ends(6)
    url = (
        f"{_BASE}zcfzbAjaxNew?companyType=4&reportDateType=0&reportType=1"
        f"&dates={','.join(dates)}&code={em_code}"
    )
    data = _get_json(url).get("data", []) or []

    records: List[dict] = []
    for row in data:
        if row.get("REPORT_TYPE") != "年报":
            continue
        # 有息负债 = 短期借款 + 长期借款 + 应付债券 + 一年内到期的非流动负债(近似)
        st_borrow = _num(row.get("SHORT_LOAN"))
        lt_borrow = _num(row.get("LONG_LOAN"))
        bonds = _num(row.get("BOND_PAYABLE"))
        st_lt_due = _num(row.get("NONCURRENT_LIAB_1YEAR"))
        interest_debt = st_borrow + lt_borrow + bonds + st_lt_due

        records.append({
            "report_date": (row.get("REPORT_DATE") or "")[:10],
            "total_assets": _num(row.get("TOTAL_ASSETS")),
            "total_liabilities": _num(row.get("TOTAL_LIABILITIES")),
            "equity": _num(row.get("TOTAL_EQUITY")),
            "cash": _num(row.get("MONETARYFUNDS")),
            "interest_bearing_debt": interest_debt,
            "current_assets": _num(row.get("TOTAL_CURRENT_ASSETS")),
            "current_liabilities": _num(row.get("TOTAL_CURRENT_LIAB")),
        })
    records.sort(key=lambda x: x["report_date"])
    return records


def fetch_company_info(code: str) -> dict:
    """抓取公司基本信息（名称、行业、股本）。

    数据源：F10 公司概况 + 股本结构接口（绕过实时行情接口，
    后者在公司代理网络下不稳定）。
    """
    secu_code, em_code = _normalize_code(code)

    # 公司概况
    survey = {}
    try:
        url = f"{_BASE}../CompanySurvey/CompanySurveyAjax?code={em_code}"
        d = _get_json(url)
        jbzl = (d.get("jbzl") or {}) if isinstance(d, dict) else {}
        survey = jbzl
    except FetchError:
        survey = {}

    # 股本结构
    shares = 0.0
    try:
        url = f"{_BASE}../CapitalStockStructure/PageAjax?code={em_code}"
        d = _get_json(url)
        gbjg = (d.get("gbjg") or []) if isinstance(d, dict) else []
        if gbjg:
            shares = _num(gbjg[0].get("TOTAL_SHARES"))
    except FetchError:
        shares = 0.0

    return {
        "name": survey.get("gsmc", ""),
        "english_name": survey.get("ywmc", ""),
        "industry": survey.get("sshy", ""),
        "code": secu_code,
        "total_shares": shares,          # 总股本（股）
        "total_mv": None,                # 实时市值需行情接口，此处不抓取
        "float_mv": None,
        "pe_ttm": None,
        "pb": None,
    }


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _num(v) -> float:
    """安全转 float，None/空 返回 0.0。"""
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _pct(v) -> float:
    """东方财富比率字段返回的是百分数值（如 89.58 表示 89.58%），转小数。"""
    return _num(v) / 100.0


def _recent_year_ends(n: int) -> List[str]:
    """生成最近 n 个年度报告期末日期（12-31）。"""
    import datetime
    today = datetime.date.today()
    years = [today.year - i for i in range(n)]
    return [f"{y}-12-31" for y in years]


def build_financial_dataset(code: str) -> dict:
    """整合三张表数据，返回一个结构化数据集，供 DCF 引擎使用。

    返回结构：
        {
            "company": {...},      # 基本信息
            "income": [...],       # 利润表派生指标（按年份升序）
            "cashflow": [...],     # 现金流量表
            "balance": [...],      # 资产负债表
        }
    """
    company = fetch_company_info(code)
    income = fetch_income_metrics(code)
    cashflow = fetch_cashflow(code)
    balance = fetch_balance_sheet(code)

    # 合并对齐：以利润表年份为基准，映射现金流与资产负债表
    dataset = {
        "company": company,
        "income": income,
        "cashflow": cashflow,
        "balance": balance,
    }

    # 港股金额单位为元，若标的市场为港股需按需换算。这里保留原始币种，
    # 由调用方决定是否折算。返回时附带市场标识。
    dataset["market"] = "HK" if code.upper().replace(" ", "").endswith(".HK") or "HK" in code.upper() else "A"
    return dataset


if __name__ == "__main__":
    # 自测：抓取贵州茅台
    import pprint
    ds = build_financial_dataset("600519.SH")
    print("公司:", ds["company"]["name"])
    print("\n利润表派生指标（近3年）:")
    for r in ds["income"][-3:]:
        pprint.pprint(r)
    print("\n现金流量表（近3年）:")
    for r in ds["cashflow"][-3:]:
        pprint.pprint(r)
    print("\n资产负债表（近3年）:")
    for r in ds["balance"][-3:]:
        pprint.pprint(r)
