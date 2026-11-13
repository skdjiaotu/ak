"""资金流向总览仪表盘 —— 每日生成。

整合三块资金数据，输出一个带「流入/流出」结论标签的交互式 HTML。

数据源：
1. 主力资金净流入（东财 push2 fflow/daykline，上证 1.000001）
2. 融资融券余额（东财 RPTA_RZRQ_LSHJ）
3. 北向资金持股市值（akshare stock_hsgt_hist_em）

⚠️ 北向持仓市值自 2026-09-30 后停更，不纳入结论判断。

用法：
    .venv/Scripts/python.exe -m fund_flow.dashboard
"""

from __future__ import annotations

import datetime
import json
import os

import requests

from fund_flow.fetcher import fetch_margin_summary, fetch_northbound_history

RED = "#e54d42"    # 流入/涨/加杠杆（A股惯例红涨）
GRN = "#3eb575"    # 流出/跌/去杠杆
AMBER = "#f5a623"

_OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports")


def _fetch_main_flow() -> list[str]:
    """抓取大盘主力资金流历史 klines（东财 push2）。"""
    s = requests.Session()
    s.trust_env = False
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": "https://data.eastmoney.com/",
    }
    url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    params = {
        "lmt": "0", "klt": "101",
        "secid": "1.000001", "secid2": "0.399001",
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        "ut": "b2884a393a59ad64002292a3e90d46a5",
    }
    r = s.get(url, params=params, headers=headers, timeout=25)
    r.raise_for_status()
    return r.json()["data"]["klines"]


def _judge(mf_net: list[float], mg_rzye: list[float]) -> tuple[str, str, list]:
    """按主力资金 + 两融两个可靠指标判断资金方向。

    返回 (结论文字, 结论颜色, 明细列表)
    """
    mf_20 = sum(mf_net[-20:])
    mg_trend = mg_rzye[-1] - mg_rzye[-20] if len(mg_rzye) >= 20 else mg_rzye[-1] - mg_rzye[0]

    signals = []
    if mf_20 < 0:
        signals.append(("主力资金(20日)", "净流出", GRN, f"{mf_20:+,.0f} 亿"))
    else:
        signals.append(("主力资金(20日)", "净流入", RED, f"{mf_20:+,.0f} 亿"))
    if mg_trend < 0:
        signals.append(("两融杠杆(20日)", "去杠杆", GRN, f"{mg_trend:+,.0f} 亿"))
    else:
        signals.append(("两融杠杆(20日)", "加杠杆", RED, f"{mg_trend:+,.0f} 亿"))

    neg = sum(1 for s in signals if s[1] in ("净流出", "去杠杆"))
    if neg == 2:
        verdict, vcolor = "资金净流出", GRN
    elif neg == 0:
        verdict, vcolor = "资金净流入", RED
    else:
        verdict, vcolor = "分歧/观望", AMBER

    return verdict, vcolor, signals


def build() -> str:
    """生成仪表盘 HTML 文件，返回输出文件路径（向后兼容）。"""
    html = build_dashboard()
    os.makedirs(_OUT, exist_ok=True)
    out = os.path.join(_OUT, "资金流向总览仪表盘.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    return out


def build_dashboard() -> str:
    """生成仪表盘 HTML 字符串（供后端 /api/dashboards/{key} 动态渲染）。"""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    mf = _fetch_main_flow()
    mg = fetch_margin_summary(pages=6, page_size=500)
    nb = fetch_northbound_history()

    # 主力资金流
    mf_dates, mf_net, mf_ratio = [], [], []
    for k in mf:
        p = k.split(",")
        mf_dates.append(p[0])
        mf_net.append(float(p[1]) / 1e8)
        mf_ratio.append(float(p[6]))

    # 两融（近4个月）
    cut = (datetime.date.today() - datetime.timedelta(days=122)).isoformat()
    mg_recent = [r for r in mg if r["date"] >= cut]
    mg_dates = [r["date"] for r in mg_recent]
    mg_rzye = [r["rzye"] / 1e8 for r in mg_recent]

    # 北向（只取持仓市值有效区间）
    nb_valid = [r for r in nb if (r["hold_mv_yuan"] or 0) > 0]
    nb_dates = [r["date"] for r in nb_valid]
    nb_hold = [r["hold_mv_yuan"] / 1e12 for r in nb_valid]
    nb_last_date = nb_valid[-1]["date"] if nb_valid else ""

    verdict, vcolor, signals = _judge(mf_net, mg_rzye)

    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=False, vertical_spacing=0.06,
        row_heights=[0.28, 0.26, 0.23, 0.23],
        subplot_titles=(
            "主力资金净流入（超大单+大单）",
            "融资余额（杠杆资金）",
            f"北向资金持股市值（{nb_last_date} 后停更）",
            "主力资金净占比（%）",
        ),
    )

    fig.add_trace(go.Bar(
        x=mf_dates, y=mf_net, name="主力净流入",
        marker_color=[RED if v >= 0 else GRN for v in mf_net],
        hovertemplate="%{x}<br>%{y:+,.0f} 亿<extra></extra>",
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=mg_dates, y=mg_rzye, name="融资余额", line=dict(color=RED, width=1.8),
        fill="tozeroy", fillcolor="rgba(229,77,66,0.10)",
        hovertemplate="%{x}<br>%{y:,.0f} 亿<extra></extra>",
    ), row=2, col=1)

    fig.add_trace(go.Scatter(
        x=nb_dates, y=nb_hold, name="北向持股市值", line=dict(color="#8e44ad", width=1.6),
        hovertemplate="%{x}<br>%{y:.2f} 万亿<extra></extra>",
    ), row=3, col=1)

    fig.add_trace(go.Scatter(
        x=mf_dates, y=mf_ratio, name="主力净占比", line=dict(color="#e67e22", width=1.4),
        hovertemplate="%{x}<br>%{y:.2f}%<extra></extra>",
    ), row=4, col=1)
    fig.add_hline(y=0, line_color="#999", line_width=1, row=4, col=1)

    fig.add_annotation(
        text=f'<b style="color:{vcolor};font-size:18px">{verdict}</b>',
        xref="paper", yref="paper", x=1.0, y=1.05, showarrow=False, xanchor="right",
    )

    fig.update_layout(
        title=dict(
            text=f'市场资金流向总览 · {datetime.date.today()}',
            x=0.02, xanchor="left", font=dict(size=19),
        ),
        height=1000, template="plotly_white", hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(size=12)),
        margin=dict(l=60, r=30, t=80, b=40),
    )
    fig.update_yaxes(title_text="亿元", row=1, col=1)
    fig.update_yaxes(title_text="亿元", row=2, col=1)
    fig.update_yaxes(title_text="万亿元", row=3, col=1)
    fig.update_yaxes(title_text="%", row=4, col=1)

    return fig.to_html(include_plotlyjs=True, full_html=True)


if __name__ == "__main__":
    path = build()
    print("已生成:", path)
