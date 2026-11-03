"""市场情绪多因子数据采集模块。

采集 7 个情绪/资金面因子，统一为「月度」频率面板（索引=月末日期，列=因子）：

  因子               数据源                                    频率    方向（高=过热/看空）
  ----               ----                                      ----    ----
  换手率 turnover     沪深300成交额/流通市值（新浪指数日线估算）  日→月   高=过热
  成交额 amount       沪深300成交量×均价（新浪指数日线）         日→月   高=过热
  融资余额 margin     东财 RPTA_RZRQ_LSHJ 两融汇总             日→月   高=过热
  新增开户数 account  中登 stock_account_statistics_em         月      高=过热
  基金发行热度 fund   东财 fund_new_found_em 按成立日聚合       月      高=过热
  股债性价比 erp      PE(乐咕 stock_index_pe_lg) + 10Y国债      月      低=估值贵/看空
  波动率指数 qvix     上交所 QVIX index_option_50etf_qvix       日→月   高=恐慌/看空

设计要点：
  - 所有因子统一到「月末」月度频率，用每因子最后一个可用值填充该月。
  - 数据源各自独立、带缓存（pickle），单源失败不拖垮整体。
  - 东财行情接口易限流，成交额/换手率走新浪源（stock_zh_index_daily）。
"""

from __future__ import annotations

import os
import pickle
import time
from datetime import datetime
from typing import Dict, Optional

import numpy as np
import pandas as pd

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")


def _ensure_cache_dir():
    os.makedirs(CACHE_DIR, exist_ok=True)


def _cache_path(name: str) -> str:
    return os.path.join(CACHE_DIR, f"{name}.pkl")


def _save_cache(name: str, obj):
    _ensure_cache_dir()
    with open(_cache_path(name), "wb") as f:
        pickle.dump(obj, f)


def _load_cache(name: str, max_age_sec: Optional[float] = None):
    p = _cache_path(name)
    if not os.path.exists(p):
        return None
    if max_age_sec is not None:
        if time.time() - os.path.getmtime(p) > max_age_sec:
            return None
    try:
        with open(p, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def _num(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 1. 换手率 + 2. 成交额（腾讯沪深300指数日线，含成交额 amount，历史完整无缺口）
# ---------------------------------------------------------------------------

def fetch_index_daily(symbol: str = "sh000300") -> pd.DataFrame:
    """沪深300指数日线（腾讯），返回 date/close/amount（成交额，单位「手」）。"""
    import akshare as ak

    df = ak.stock_zh_index_daily_tx(symbol=symbol)
    df = df.sort_values("date").reset_index(drop=True)
    df["date"] = pd.to_datetime(df["date"])
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    return df[["date", "close", "amount"]]


# 沪深300自由流通股本（亿股），用于把「成交股数」换算成换手率。
# 真实值约 3~4.5 万亿股；此处为常数近似，只影响绝对量级，不影响趋势/分位。
HS300_FLOAT_SHARES_YI = 44000.0  # 亿股


def build_turnover_amount(index_daily: pd.DataFrame) -> pd.DataFrame:
    """由指数日线生成换手率与成交额（日频）。

    成交额 amount：腾讯源直接给出（单位「手」，1手=100股），转为「亿手」口径
      用于展示，但策略仅用其趋势/分位，绝对量级无关紧要。
    换手率 = 成交股数 / 自由流通股本(股)，量级 1e-3 附近。
    """
    df = index_daily.copy()
    df["amount_yi_shou"] = df["amount"] / 1e8  # 亿手（1手=100股，展示用）
    # 换手率 = 成交额(手) × 100(股/手) / 自由流通股本(股)
    df["turnover"] = df["amount"] * 100.0 / (HS300_FLOAT_SHARES_YI * 1e8)
    return df[["date", "amount", "amount_yi_shou", "turnover"]]


# ---------------------------------------------------------------------------
# 3. 融资余额（东财两融汇总，复用 fund_flow 口径）
# ---------------------------------------------------------------------------

def fetch_margin_balance() -> pd.DataFrame:
    """融资余额日频（东财 RPTA_RZRQ_LSHJ），返回 date/rzye(元)。"""
    import requests

    s = requests.Session()
    s.trust_env = False
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}
    rows = []
    for p in range(1, 8):
        params = {
            "reportName": "RPTA_RZRQ_LSHJ", "columns": "ALL",
            "pageNumber": p, "pageSize": 500,
            "sortColumns": "DIM_DATE", "sortTypes": -1,
            "source": "WEB", "client": "WEB",
        }
        try:
            r = s.get(url, params=params, headers=headers, timeout=25)
            d = r.json()
        except Exception:
            break
        data = (d.get("result") or {}).get("data") or []
        if not data:
            break
        for row in data:
            rzye = _num(row.get("RZYE"))
            if rzye:
                rows.append((str(row.get("DIM_DATE", ""))[:10], rzye))
        if len(data) < 500:
            break
    df = pd.DataFrame(rows, columns=["date", "rzye"])
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").drop_duplicates("date")


# ---------------------------------------------------------------------------
# 4. 新增开户数（中登，月度）
# ---------------------------------------------------------------------------

def fetch_account() -> pd.DataFrame:
    """新增开户数（月度，万户），返回 date/new_account（date=月末）。"""
    import akshare as ak

    df = ak.stock_account_statistics_em()
    # "2023-06" 这类字符串转 period 再转月末时间戳，保证与其它因子月末对齐
    ym = pd.to_datetime(df["数据日期"].astype(str)).dt.to_period("M")
    out = pd.DataFrame({
        "date": ym.dt.to_timestamp("M"),
        "new_account": df["新增投资者-数量"].astype(float),
    })
    return out.sort_values("date")


# ---------------------------------------------------------------------------
# 5. 基金发行热度（东财新发基金，按成立日聚合为月度）
# ---------------------------------------------------------------------------

def fetch_fund_issue() -> pd.DataFrame:
    """基金发行热度（月度），返回 date/fund_count(只数)/fund_share(募集份额亿份)。"""
    import akshare as ak

    df = ak.fund_new_found_em()
    df = df.copy()
    df["成立日期"] = pd.to_datetime(df["成立日期"], errors="coerce")
    df = df.dropna(subset=["成立日期"])
    df["募集份额"] = pd.to_numeric(df["募集份额"], errors="coerce").fillna(0)
    df["ym"] = df["成立日期"].dt.to_period("M")
    g = df.groupby("ym").agg(
        fund_count=("基金简称", "count"),
        fund_share=("募集份额", "sum"),
    )
    g["date"] = g.index.to_timestamp("M")
    return g.reset_index(drop=True)[["date", "fund_count", "fund_share"]]


# ---------------------------------------------------------------------------
# 6. 股债性价比（1/PE - 10Y国债收益率，月度）
# ---------------------------------------------------------------------------

def fetch_erp() -> pd.DataFrame:
    """股债性价比 ERP（月度），返回 date/erp。

    ERP = 沪深300滚动市盈率倒数 - 中国10年国债收益率(%)。
    ERP 越高代表股票相对债券越有吸引力（估值便宜）。
    """
    import akshare as ak

    pe = ak.stock_index_pe_lg(symbol="沪深300")
    pe = pe[["日期", "滚动市盈率"]].rename(columns={"日期": "date", "滚动市盈率": "pe"})
    pe["date"] = pd.to_datetime(pe["date"])
    pe["pe"] = pd.to_numeric(pe["pe"], errors="coerce")

    bond = ak.bond_zh_us_rate()
    bond = bond[["日期", "中国国债收益率10年"]].rename(
        columns={"日期": "date", "中国国债收益率10年": "y10"})
    bond["date"] = pd.to_datetime(bond["date"])
    bond["y10"] = pd.to_numeric(bond["y10"], errors="coerce")

    m = pe.merge(bond, on="date", how="inner")
    m = m.dropna(subset=["pe", "y10"])
    m = m[m["pe"] > 0]
    m["erp"] = 100.0 / m["pe"] - m["y10"]  # 百分比口径
    return m[["date", "erp"]]


# ---------------------------------------------------------------------------
# 7. 波动率指数 QVIX（上交所 50ETF 期权隐含波动率，日频，反向指标）
# ---------------------------------------------------------------------------
# 7. 波动率因子（历史波动率 HV20，替代不稳定的 QVIX）
# ---------------------------------------------------------------------------

def build_volatility(index_daily: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """基于沪深300日线计算 20 日年化历史波动率（日频），返回 date/qvix。

    说明：QVIX（上交所隐含波动率指数，1.optbbs.com）接口极不稳定（403/超时），
    故改用「20 日年化历史波动率」作为波动率/恐慌因子。两者逻辑等价——
    波动率越高 = 市场越恐慌 = 越该逆向买入。数据源为腾讯日线，稳定且历史完整。
    """
    df = index_daily.sort_values("date").copy()
    df["logret"] = np.log(df["close"]).diff()
    df["hv"] = df["logret"].rolling(window).std() * np.sqrt(252) * 100  # 年化 %
    out = df[["date", "hv"]].rename(columns={"hv": "qvix"})
    return out


def fetch_qvix(retries: int = 2, delay: float = 5.0) -> pd.DataFrame:
    """50ETF QVIX 波动率指数（日频），返回 date/qvix。

    该接口（1.optbbs.com）极不稳定（403/超时），仅作可选增强；
    主用 build_volatility 的历史波动率兜底。
    """
    import akshare as ak

    last_err = None
    for i in range(retries):
        try:
            df = ak.index_option_50etf_qvix()
            df = df[["date", "close"]].rename(columns={"close": "qvix"})
            df["date"] = pd.to_datetime(df["date"])
            return df.sort_values("date").drop_duplicates("date")
        except Exception as e:
            last_err = e
            time.sleep(delay)
    raise RuntimeError(f"QVIX 拉取失败（重试{retries}次）: {last_err}")


# ---------------------------------------------------------------------------
# 月度面板组装
# ---------------------------------------------------------------------------

def _to_month_end(series: pd.DataFrame, date_col: str, val_col: str) -> pd.Series:
    """日频 → 月度（取每自然月最后一个值），返回以月末日期为索引的 Series。"""
    s = series.dropna(subset=[val_col]).copy()
    s = s.set_index(date_col)[val_col]
    s.index = pd.to_datetime(s.index).normalize()
    out = s.resample("ME").last().dropna()
    out.index = out.index.normalize()
    return out


def build_monthly_panel(cache: bool = True, max_age_sec: float = 24 * 3600) -> pd.DataFrame:
    """组装 7 因子月度面板。

    返回 DataFrame，索引=月末日期，列：
      turnover, amount, margin, new_account, fund_count, fund_share, erp, qvix
    """
    parts: Dict[str, pd.Series] = {}

    # 1+2. 换手率 + 成交额（新浪沪深300日线）
    idx = _load_cache("index_daily", max_age_sec)
    if idx is None:
        idx = fetch_index_daily()
        _save_cache("index_daily", idx)
    ta = build_turnover_amount(idx)
    parts["turnover"] = _to_month_end(ta, "date", "turnover")
    parts["amount"] = _to_month_end(ta, "date", "amount")

    # 3. 融资余额
    mg = _load_cache("margin", max_age_sec)
    if mg is None:
        mg = fetch_margin_balance()
        _save_cache("margin", mg)
    parts["margin"] = _to_month_end(mg, "date", "rzye")

    # 4. 新增开户数
    acc = _load_cache("account", max_age_sec * 30)
    if acc is None:
        acc = fetch_account()
        _save_cache("account", acc)
    parts["new_account"] = acc.set_index("date")["new_account"]

    # 5. 基金发行热度
    fund = _load_cache("fund", max_age_sec * 30)
    if fund is None:
        fund = fetch_fund_issue()
        _save_cache("fund", fund)
    parts["fund_count"] = fund.set_index("date")["fund_count"]
    parts["fund_share"] = fund.set_index("date")["fund_share"]

    # 6. 股债性价比（本身月度，但月末日可能不齐，统一 resample 到 ME）
    erp = _load_cache("erp", max_age_sec * 30)
    if erp is None:
        erp = fetch_erp()
        _save_cache("erp", erp)
    parts["erp"] = _to_month_end(erp, "date", "erp")

    # 7. 波动率（历史波动率 HV20 兜底，QVIX 失败时自动降级）
    qvix = _load_cache("qvix", max_age_sec * 30)
    if qvix is None:
        # 优先尝试 QVIX（增强），失败则用历史波动率兜底
        try:
            qvix = fetch_qvix()
        except Exception:
            qvix = build_volatility(idx)
        _save_cache("qvix", qvix)
    parts["qvix"] = _to_month_end(qvix, "date", "qvix")

    panel = pd.DataFrame(parts)
    panel = panel.sort_index()
    return panel


if __name__ == "__main__":
    p = build_monthly_panel(cache=False)
    print(f"月度面板: {p.shape[0]} 行 × {p.shape[1]} 列")
    print(f"区间: {p.index[0].date()} ~ {p.index[-1].date()}")
    print(p.tail(6).round(3).to_string())
