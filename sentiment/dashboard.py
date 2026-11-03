"""市场情绪多因子驾驶舱 —— 静态 HTML 看板生成器。

复用 sentiment 引擎数据，产出一个自包含的 HTML 驾驶舱页面，包含：
  1. 综合情绪仪表盘（半圆仪表）
  2. 7 因子状态卡（当前值 + 近3年分位 + 方向）
  3. 择时回测绩效（买入持有 vs 情绪择时 vs 反向对照）
  4. 单因子有效性（IC 与方向）
  5. 历史净值曲线 + 仓位曲线（ECharts）

用法：
    .venv/Scripts/python.exe -m sentiment.dashboard

输出：reports/市场情绪驾驶舱_YYYY-MM-DD.html
"""

from __future__ import annotations

import json
import os
from datetime import datetime

import numpy as np
import pandas as pd

from sentiment.fetcher import build_monthly_panel
from sentiment.engine import (build_factor_scores, composite_heat,
                              heat_to_position, current_status,
                              factor_effectiveness, FACTOR_CN, FACTOR_SIGN)
from sentiment.backtest import (fetch_benchmark_index, backtest_compare,
                                backtest)

REPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "..", "reports")


def _pct(v, nd=1):
    return "N/A" if v is None else f"{v * 100:.{nd}f}%"


def _num(v, nd=2):
    if v is None:
        return "N/A"
    if abs(v) >= 1e12:
        return f"{v/1e12:.{nd}f}万亿"
    if abs(v) >= 1e8:
        return f"{v/1e8:.{nd}f}亿"
    if abs(v) >= 1e4:
        return f"{v/1e4:.{nd}f}万"
    return f"{v:.{nd}f}"


def _factor_value_str(col, v):
    """按因子类型格式化当前值。"""
    if col == "margin":
        return f"{v/1e8:.0f} 亿元"
    if col == "new_account":
        return f"{v:.1f} 万户"
    if col == "fund_count":
        return f"{v:.0f} 只"
    if col == "fund_share":
        return f"{v:.0f} 亿份"
    if col == "erp":
        return f"{v:.2f}%"
    if col == "qvix":
        return f"{v:.1f}%"
    if col == "turnover":
        return f"{v*100:.2f}%"
    if col == "amount":
        return _num(v, 1)
    return f"{v:.3g}"


def _heat_gauge_color(heat):
    """情绪热度 → 颜色（红=过热，绿=冰点，符合A股涨红跌绿习惯但语义相反）。"""
    if heat >= 1.0:
        return "#e24b4a"  # 过热
    if heat <= -1.0:
        return "#1d9e75"  # 冰点
    return "#ba7517"      # 中性


def _heat_label(heat):
    if heat >= 1.0:
        return "过热 · 减仓"
    if heat >= 0.5:
        return "偏热 · 谨慎"
    if heat <= -1.0:
        return "冰点 · 加仓"
    if heat <= -0.5:
        return "偏冷 · 布局"
    return "中性 · 观望"


def _factor_status_html(col, d):
    """单因子状态卡 HTML。"""
    pct = d["pct"]
    if pct >= 80:
        lvl = "high"
    elif pct <= 20:
        lvl = "low"
    else:
        lvl = "mid"
    sign = d["sign"]
    if sign > 0:
        hot = "情绪热度"
        hot_cls = "hot"
    else:
        hot = "逆向估值"
        hot_cls = "inv"
    return f"""
      <div class="fcard {lvl}">
        <div class="fname">{d['cn']}</div>
        <div class="fval">{_factor_value_str(col, d['value'])}</div>
        <div class="fbar"><div class="fbar-fill" style="width:{pct:.0f}%"></div></div>
        <div class="fmeta">
          <span>近3年分位 <b>{pct:.0f}%</b></span>
          <span class="tag {hot_cls}">{hot}</span>
        </div>
      </div>"""


def build_dashboard() -> str:
    """生成驾驶舱 HTML 字符串。"""
    panel = build_monthly_panel()
    bench = fetch_benchmark_index()

    scores = build_factor_scores(panel, window=24)
    heat = composite_heat(scores)
    pos = heat_to_position(heat, overheat=1.0, ice=-1.0)

    cmp = backtest_compare(panel, pos, bench)
    b, s, iv = cmp["bench"], cmp["strat"], cmp["inverse"]

    idx = bench.set_index("date")["close"]
    fwd = idx.pct_change().shift(-1)
    eff = factor_effectiveness(scores, fwd)

    snap = current_status(panel, scores, heat)

    last_heat = heat.dropna().iloc[-1]
    last_pos = pos.dropna().iloc[-1]
    last_date = panel.index[-1].strftime("%Y-%m-%d")

    # ---- 历史净值/仓位曲线数据（ECharts）----
    res = backtest(panel, pos, bench)
    equity_bench = (1 + res["bench_ret"]).cumprod()
    equity_strat = (1 + res["strat_ret"]).cumprod()
    dates = [d.strftime("%Y-%m") for d in res.index]

    # ---- 因子状态卡 ----
    factor_cards = "".join(_factor_status_html(c, d) for c, d in snap.items())

    # ---- 因子有效性表 ----
    eff_rows = ""
    for _, r in eff.iterrows():
        mark = "✓" if r["符合预期"] else "✗"
        cls = "ok" if r["符合预期"] else "bad"
        eff_rows += (f"<tr><td>{r['因子']}</td>"
                     f"<td class='ic'>{r['IC']:+.3f}</td>"
                     f"<td class='{cls}'>{mark}</td></tr>")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>市场情绪驾驶舱 {last_date}</title>
<script src="/static/echarts.min.js"></script>
<style>
  :root {{
    --bg: #f5f6f8; --card: #ffffff; --text: #1a1a1a; --muted: #888;
    --red: #e24b4a; --green: #1d9e75; --yellow: #ba7517;
    --border: #e5e7eb;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
         background: var(--bg); color: var(--text); line-height: 1.6; padding: 20px; }}
  .wrap {{ max-width: 1200px; margin: 0 auto; }}
  .head {{ display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap;
          margin-bottom: 18px; }}
  h1 {{ font-size: 24px; font-weight: 700; }}
  .sub {{ color: var(--muted); font-size: 13px; }}
  .grid {{ display: grid; gap: 16px; }}
  .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 14px;
           padding: 18px; }}
  h2 {{ font-size: 15px; font-weight: 600; margin-bottom: 14px; color: #333; }}
  h2 .badge {{ font-size: 12px; font-weight: 500; color: var(--muted); margin-left: 8px; }}

  /* 顶部三列 */
  .top {{ display: grid; grid-template-columns: 1.1fr 1.4fr 1fr; gap: 16px; }}
  @media (max-width: 900px) {{ .top {{ grid-template-columns: 1fr; }} }}

  /* 仪表盘 */
  .gauge-box {{ display: flex; flex-direction: column; align-items: center; }}
  #gauge {{ width: 100%; height: 200px; }}
  .gauge-label {{ text-align: center; margin-top: -6px; }}
  .gauge-label .big {{ font-size: 30px; font-weight: 700; }}
  .pos-rec {{ margin-top: 12px; text-align: center; font-size: 14px; }}
  .pos-rec .pct {{ font-size: 26px; font-weight: 700; }}

  /* KPI 数字 */
  .kpis {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
  .kpi {{ background: #fafbfc; border: 1px solid var(--border); border-radius: 10px;
          padding: 12px; }}
  .kpi .k {{ color: var(--muted); font-size: 12px; }}
  .kpi .v {{ font-size: 22px; font-weight: 700; margin-top: 2px; }}
  .kpi .d {{ font-size: 11px; color: var(--muted); }}

  /* 因子状态卡 */
  .factors {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }}
  @media (max-width: 900px) {{ .factors {{ grid-template-columns: repeat(2, 1fr); }} }}
  .fcard {{ border: 1px solid var(--border); border-radius: 10px; padding: 12px;
            border-left: 3px solid #ccc; background: #fafbfc; }}
  .fcard.high {{ border-left-color: var(--red); }}
  .fcard.low {{ border-left-color: var(--green); }}
  .fcard.mid {{ border-left-color: var(--yellow); }}
  .fname {{ font-size: 13px; color: var(--muted); }}
  .fval {{ font-size: 20px; font-weight: 700; margin: 4px 0; }}
  .fbar {{ height: 5px; background: #eee; border-radius: 3px; overflow: hidden; }}
  .fbar-fill {{ height: 100%; background: #94a3b8; border-radius: 3px; }}
  .fcard.high .fbar-fill {{ background: var(--red); }}
  .fcard.low .fbar-fill {{ background: var(--green); }}
  .fmeta {{ display: flex; justify-content: space-between; align-items: center;
            margin-top: 8px; font-size: 11px; color: var(--muted); }}
  .tag {{ padding: 1px 8px; border-radius: 12px; font-size: 11px; }}
  .tag.hot {{ background: #fcebeb; color: #a32d2d; }}
  .tag.inv {{ background: #e1f5ee; color: #0f6e56; }}

  /* 图表 */
  .chart {{ width: 100%; height: 320px; }}

  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ padding: 7px 10px; text-align: right; border-bottom: 1px solid var(--border); }}
  th {{ color: var(--muted); font-weight: 500; font-size: 12px; }}
  th:first-child, td:first-child {{ text-align: left; }}
  td.ok {{ color: var(--green); font-weight: 600; }}
  td.bad {{ color: var(--red); font-weight: 600; }}
  td.ic {{ font-weight: 600; }}

  .two {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  @media (max-width: 900px) {{ .two {{ grid-template-columns: 1fr; }} }}

  .note {{ background: #fff8e6; border-left: 4px solid #ef9f27; padding: 10px 14px;
           border-radius: 8px; font-size: 13px; margin-top: 12px; }}
  .footer {{ text-align: center; color: var(--muted); font-size: 12px; margin-top: 20px; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="head">
    <div>
      <h1>市场情绪驾驶舱</h1>
      <div class="sub">数据截至 {last_date} ｜ 七因子：换手率·成交额·融资余额·新增开户·基金发行·股债性价比·波动率</div>
    </div>
  </div>

  <!-- 顶部：仪表盘 + KPI + 综合判定 -->
  <div class="top">
    <div class="card gauge-box">
      <h2>综合情绪热度</h2>
      <div id="gauge"></div>
      <div class="gauge-label">
        <span class="big" style="color:{_heat_gauge_color(last_heat)}">{_heat_label(last_heat)}</span>
      </div>
      <div class="pos-rec">
        建议仓位 <span class="pct" style="color:{_heat_gauge_color(last_heat)}">{last_pos*100:.0f}%</span>
      </div>
    </div>

    <div class="card">
      <h2>择时回测绩效 <span class="badge">沪深300 · 月度 · 无杠杆</span></h2>
      <div class="kpis">
        <div class="kpi"><div class="k">策略累计收益</div>
          <div class="v" style="color:{'var(--red)' if s['total']>=0 else 'var(--green)'}">{_pct(s['total'],0)}</div>
          <div class="d">买入持有 {_pct(b['total'],0)}</div></div>
        <div class="kpi"><div class="k">策略年化</div>
          <div class="v">{_pct(s['ann'])}</div>
          <div class="d">买入持有 {_pct(b['ann'])}</div></div>
        <div class="kpi"><div class="k">最大回撤</div>
          <div class="v">{_pct(s['max_dd'])}</div>
          <div class="d">买入持有 {_pct(b['max_dd'])}</div></div>
        <div class="kpi"><div class="k">夏普比率</div>
          <div class="v">{s['sharpe']:.2f}</div>
          <div class="d">平均仓位 {_pct(cmp['avg_pos'],0)}</div></div>
      </div>
    </div>

    <div class="card">
      <h2>策略结论</h2>
      <div style="font-size:13px; line-height:1.9">
        <p>本策略为<b>情绪逆向择时</b>：情绪过热→减仓，冰点→加仓。</p>
        <p style="margin-top:8px">回测揭示一个关键事实：<b>A股近20年动量/趋势效应强于逆向均值回归</b>，
        情绪冰点未必是买点。反向信号（追涨杀跌）累计 {_pct(iv['total'],0)}，显著优于逆向策略。</p>
      </div>
      <div class="note">结论：情绪因子更适合作为<b>风险警示</b>（识别过热），而非直接反向抄底。</div>
    </div>
  </div>

  <!-- 因子状态卡 -->
  <div class="card" style="margin-top:16px">
    <h2>七因子状态 <span class="badge">红=高位/过热 · 绿=低位/冰点 · 黄=中性</span></h2>
    <div class="factors">{factor_cards}</div>
  </div>

  <!-- 净值曲线 + 仓位曲线 -->
  <div class="two" style="margin-top:16px">
    <div class="card">
      <h2>策略 vs 买入持有净值</h2>
      <div id="nav" class="chart"></div>
    </div>
    <div class="card">
      <h2>历史仓位曲线</h2>
      <div id="pos" class="chart"></div>
    </div>
  </div>

  <!-- 因子有效性 -->
  <div class="card" style="margin-top:16px">
    <h2>单因子有效性（IC：因子信号 vs 未来1月收益）</h2>
    <table>
      <thead><tr><th>因子</th><th>IC</th><th>方向符合</th></tr></thead>
      <tbody>{eff_rows}</tbody>
    </table>
    <div class="note">IC&gt;0 表示因子值越高未来收益越高。换手率/成交额/开户数 IC 为正，
    印证 A 股「越热越涨」的动量特征；股债性价比/波动率为逆向因子，IC 为正则代表逆向逻辑成立。</div>
  </div>

  <div class="footer">本驾驶舱基于公开数据量化生成，仅供研究参考，不构成投资建议。</div>
</div>

<script>
  // 情绪仪表盘（-2 ~ +2 区间映射到半圆）
  (function(){{
    var heat = {last_heat:.4f};
    var chart = echarts.init(document.getElementById('gauge'));
    chart.setOption({{
      series: [{{
        type: 'gauge', startAngle: 210, endAngle: -30, min: -2, max: 2,
        axisLine: {{ lineStyle: {{ width: 16, color: [[0.25,'#1d9e75'],[0.5,'#e8d21d'],[0.75,'#f09a3a'],[1,'#e24b4a']] }} }},
        pointer: {{ width: 5, length: '60%', itemStyle: {{ color: 'auto' }} }},
        axisTick: {{ show: false }}, splitLine: {{ length: 12, lineStyle: {{ color: '#999', width: 2 }} }},
        axisLabel: {{ distance: 20, fontSize: 10, formatter: function(v){{ return v.toFixed(0); }} }},
        detail: {{ formatter: '{{value|.2f}}', fontSize: 28, offsetCenter: [0, '55%'],
                   color: '{_heat_gauge_color(last_heat)}' }},
        data: [{{ value: heat, name: '情绪热度' }}]
      }}]
    }});
  }})();

  // 净值曲线
  (function(){{
    var chart = echarts.init(document.getElementById('nav'));
    chart.setOption({{
      tooltip: {{ trigger: 'axis' }},
      legend: {{ data: ['买入持有','情绪择时'], top: 0 }},
      grid: {{ left: 50, right: 20, top: 30, bottom: 30 }},
      xAxis: {{ type: 'category', data: {json.dumps(dates)}, boundaryGap: false }},
      yAxis: {{ type: 'value', scale: true, axisLabel: {{ formatter: '{{value}}' }} }},
      series: [
        {{ name: '买入持有', type: 'line', data: {json.dumps([round(float(x),3) for x in equity_bench.values])},
           showSymbol: false, lineStyle: {{ width: 1.5, color: '#94a3b8' }}, itemStyle: {{ color: '#94a3b8' }} }},
        {{ name: '情绪择时', type: 'line', data: {json.dumps([round(float(x),3) for x in equity_strat.values])},
           showSymbol: false, lineStyle: {{ width: 2, color: '#e24b4a' }}, itemStyle: {{ color: '#e24b4a' }},
           areaStyle: {{ opacity: 0.08, color: '#e24b4a' }} }}
      ]
    }});
  }})();

  // 仓位曲线
  (function(){{
    var chart = echarts.init(document.getElementById('pos'));
    var pv = {json.dumps([round(float(x),2) for x in res['position'].fillna(0).values])};
    chart.setOption({{
      tooltip: {{ trigger: 'axis' }},
      grid: {{ left: 50, right: 20, top: 30, bottom: 30 }},
      xAxis: {{ type: 'category', data: {json.dumps(dates)}, boundaryGap: false }},
      yAxis: {{ type: 'value', min: 0, max: 1, axisLabel: {{ formatter: '{{value|.0}}' }} }},
      series: [{{
        name: '仓位', type: 'line', data: pv, showSymbol: false, step: 'end',
        lineStyle: {{ width: 1.5, color: '#1d9e75' }}, itemStyle: {{ color: '#1d9e75' }},
        areaStyle: {{ opacity: 0.15, color: '#1d9e75' }}
      }}]
    }});
  }})();
</script>
</body>
</html>"""
    return html


def main():
    html = build_dashboard()
    os.makedirs(REPORT_DIR, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(REPORT_DIR, f"市场情绪驾驶舱_{date_str}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"驾驶舱已生成：{path}")


if __name__ == "__main__":
    main()
