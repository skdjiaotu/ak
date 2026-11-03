"""资金面数据采集模块 —— 北向资金 + 融资融券。

核心目标：穿透"官方一片欣欣向荣"的表象，看真实资金动向。

数据源：
1. 北向资金（沪深港通）：东财 stock_hsgt_hist_em
   ⚠️ 关键事实：2024-08-19 起沪深交易所停止披露北向"当日净买入"，
   仅保留成交额与持股市值。净买入字段在此之后为 NaN —— 这本身就是
   "官方隐藏真实资金流向"的铁证，本模块会显式暴露这一点。
2. 融资融券（两融）：东财 RPTA_RZRQ_LSHJ 每日汇总接口
   融资余额 = 杠杆做多规模；融资买入额 = 情绪热度；融券余额 = 做空力量。
"""

from __future__ import annotations

import requests
from typing import Dict, List, Optional


_TIMEOUT = 25
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://data.eastmoney.com/",
}


class FetchError(Exception):
    pass


def _session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False  # 绕过系统代理（代理对东财域名不稳定）
    return s


def _num(v) -> Optional[float]:
    """安全转数值，NaN/None 返回 None。"""
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
# 北向资金
# ---------------------------------------------------------------------------

def fetch_northbound_history() -> List[Dict]:
    """抓取北向资金历史数据（东财）。

    返回按日期升序的列表，每条含：
      date, net_buy(当日成交净买额, 元, 2024-08-19后为None),
      buy_amount, sell_amount, cum_net_buy(历史累计净买额),
      hold_mv(持股市值), hold_ratio(占流通市值比, 若可用)
    """
    import akshare as ak

    df = ak.stock_hsgt_hist_em(symbol="北向资金")
    rows: List[Dict] = []
    for _, r in df.iterrows():
        # 单位说明（东财口径）：
        #   当日成交净买额 / 买入成交额 / 卖出成交额 → 亿元
        #   历史累计净买额 → 万亿元
        #   持股市值 → 元
        # 2024-08-19 起官方停止披露，东财将上述字段全部填 0（非 NaN）。
        rows.append({
            "date": str(r["日期"]),
            "net_buy_yi": _num(r.get("当日成交净买额")),       # 亿元
            "buy_amount_yi": _num(r.get("买入成交额")),        # 亿元
            "sell_amount_yi": _num(r.get("卖出成交额")),       # 亿元
            "cum_net_buy_wanyi": _num(r.get("历史累计净买额")),  # 万亿元
            "hold_mv_yuan": _num(r.get("持股市值")),           # 元
        })
    # 升序
    rows.sort(key=lambda x: x["date"])
    return rows


def _northbound_disclosure_status(rows: List[Dict]) -> Dict:
    """识别北向净买入数据的披露截止点。

    停更后东财将净买入等字段填为 None（NaN）。首个 None 日期即停更首日。
    """
    last_date = None
    first_nan_date = None
    for r in rows:
        nb = r.get("net_buy_yi")
        if nb is not None:
            last_date = r["date"]
        elif first_nan_date is None:
            first_nan_date = r["date"]
    return {"last_net_buy_date": last_date, "first_nan_date": first_nan_date}


# ---------------------------------------------------------------------------
# 融资融券
# ---------------------------------------------------------------------------

def fetch_margin_summary(pages: int = 1, page_size: int = 500) -> List[Dict]:
    """抓取两融每日汇总（东财 RPTA_RZRQ_LSHJ），沪深两市合计。

    返回按日期升序的列表，每条含：
      date, rzye(融资余额), rzmre(融资买入额), rzyezb(融资余额占流通市值比%),
      rqye(融券余额), rzrqye(融资融券余额合计), ltsz(流通市值), zdf(涨跌幅)
    """
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    s = _session()
    all_rows: List[Dict] = []
    for p in range(1, pages + 1):
        params = {
            "reportName": "RPTA_RZRQ_LSHJ",
            "columns": "ALL",
            "pageNumber": p,
            "pageSize": page_size,
            "sortColumns": "DIM_DATE",
            "sortTypes": -1,
            "source": "WEB",
            "client": "WEB",
        }
        try:
            r = s.get(url, params=params, headers=_HEADERS, timeout=_TIMEOUT)
            r.raise_for_status()
            d = r.json()
        except (requests.RequestException, ValueError) as e:
            raise FetchError(f"两融接口请求失败: {e}") from e
        result = d.get("result")
        if not result:
            break
        for row in result.get("data") or []:
            all_rows.append({
                "date": str(row.get("DIM_DATE", ""))[:10],
                "rzye": _num(row.get("RZYE")),        # 融资余额（元）
                "rzmre": _num(row.get("RZMRE")),      # 融资买入额（元）
                "rzyezb": _num(row.get("RZYEZB")),    # 融资余额占流通市值比 %
                "rqye": _num(row.get("RQYE")),        # 融券余额（元）
                "rzrqye": _num(row.get("RZRQYE")),    # 两融余额合计
                "ltsz": _num(row.get("LTSZ")),        # 流通市值（元）
                "zdf": _num(row.get("ZDF")),          # 涨跌幅 %
            })
        if len(result.get("data") or []) < page_size:
            break
    all_rows.sort(key=lambda x: x["date"])
    return all_rows


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------

def fetch_all() -> Dict:
    """一次性抓取全部资金面数据。"""
    nb = fetch_northbound_history()
    return {
        "northbound": nb,
        "northbound_status": _northbound_disclosure_status(nb),
        "margin": fetch_margin_summary(pages=6, page_size=500),
    }


if __name__ == "__main__":
    data = fetch_all()
    nb = data["northbound"]
    mg = data["margin"]
    print(f"北向资金历史: {len(nb)} 条, 最新 {nb[-1]['date'] if nb else '无'}")
    print(f"  净买入最后披露: {data['northbound_status']}")
    print(f"两融汇总: {len(mg)} 条, 最新 {mg[-1]['date'] if mg else '无'}")
    if mg:
        last = mg[-1]
        print(f"  最新融资余额: {last['rzye']/1e8:.1f} 亿, 融资买入额 {last['rzmre']/1e8:.1f} 亿, 融券余额 {last['rqye']/1e8:.1f} 亿")
