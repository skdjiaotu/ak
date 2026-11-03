"""创业板位置驾驶舱 —— 静态 HTML 看板生成器。

复用 gem_position 引擎，生成可视化驾驶舱，包含：
  1. 位置温度仪表盘（0~100，越高越危险）
  2. 五档信号 + 建议仓位
  3. 价格分位 / 估值分位 / 距高点回撤三要素
  4. 历史点位 + 位置分位曲线（ECharts）

用法：
    .venv/Scripts/python.exe -m gem_position.dashboard

输出：reports/创业板位置驾驶舱_YYYY-MM-DD.html
"""

from __future__ import annotations

import json
import os
from datetime import datetime

from gem_position.fetcher import build_gem_dataset
from gem_position.engine import assess_position, build_position_series

REPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "..", "reports")


def _pct(v, nd=1):
    return "N/A" if v is None else f"{v * 100:.{nd}f}%"


def _temp_color(temp):
    if temp is None:
        return "#888"
    if temp >= 80:
        return "#e24b4a"
    if temp >= 60:
        return "#e8752a"
    if temp >= 40:
        return "#ba7517"
    return "#1d9e75"


def _temp_label(temp):
    if temp is None:
        return "数据不足"
    if temp >= 80:
        return "高位 · 高风险"
    if temp >= 60:
        return "偏高 · 谨慎"
    if temp >= 40:
        return "中性 · 观望"
    if temp >= 20:
        return "偏低 · 布局"
    return "低位 · 建仓"


def build_dashboard() -> str:
    ds = build_gem_dataset()
    r = assess_position(ds)
    series = build_position_series(ds["kline"], window=1250)

    temp = r["position_temp"]
    color = _temp_color(temp)
    last_date = r["last_date"]
    cur = ds["current"]

    # 三要素卡
    comp = r["components"]
    def _comp_row(key, label, disp, sub=""):
        v = comp.get(key)
        if v is None:
            return ""
        return (f"<div class='comp'><div class='ck'>{label}</div>"
                f"<div class='cv'>{v:.1f}<span class='cu'>/100</span></div>"
                f"<div class='cd'>{disp}{sub}</div>"
                f"<div class='cbar'><div class='cbar-fill' style='width:{v:.0f}%'></div></div></div>")

    comp_html = ""
    comp_html += _comp_row("price", "价格分位", f"近5年 {_pct(r['price_pct_5y'])}",
                           f" ｜ 全历史 {_pct(r['price_pct_all'])}")
    comp_html += _comp_row("pe", "估值分位", f"PE {r['pe_ttm']:.2f} 倍",
                           f" ｜ 分位 {_pct(r['pe_pct'])}")
    comp_html += _comp_row("drawdown", "距高点回撤", f"距5年高 -{abs(r['dd_from_5y']*100):.1f}%",
                           f" ｜ 高点 {r['high_5y']:.0f}")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>创业板位置驾驶舱 {last_date}</title>
<script src="/static/echarts.min.js"></script>
<style>
  :root {{
    --bg: #f5f6f8; --card: #ffffff; --text: #1a1a1a; --muted: #888;
    --red: #e24b4a; --orange: #e8752a; --yellow: #ba7517; --green: #1d9e75;
    --border: #e5e7eb;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
         background: var(--bg); color: var(--text); line-height: 1.6; padding: 20px; }}
  .wrap {{ max-width: 1100px; margin: 0 auto; }}
  .head {{ margin-bottom: 18px; }}
  h1 {{ font-size: 23px; font-weight: 700; }}
  .sub {{ color: var(--muted); font-size: 13px; margin-top: 4px; }}
  .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 14px;
           padding: 20px; }}
  h2 {{ font-size: 15px; font-weight: 600; margin-bottom: 14px; color: #333; }}

  .top {{ display: grid; grid-template-columns: 1.1fr 1.4fr 1fr; gap: 16px; }}
  @media (max-width: 900px) {{ .top {{ grid-template-columns: 1fr; }} }}

  .gauge-box {{ display: flex; flex-direction: column; align-items: center; }}
  #gauge {{ width: 100%; height: 210px; }}
  .gauge-label {{ text-align: center; margin-top: -4px; }}
  .gauge-label .big {{ font-size: 28px; font-weight: 700; }}
  .pos-rec {{ margin-top: 10px; text-align: center; font-size: 14px; }}
  .pos-rec .pct {{ font-size: 24px; font-weight: 700; }}

  .comps {{ display: flex; flex-direction: column; gap: 12px; }}
  .comp {{ border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px;
           background: #fafbfc; }}
  .ck {{ font-size: 12px; color: var(--muted); }}
  .cv {{ font-size: 22px; font-weight: 700; }}
  .cu {{ font-size: 12px; color: var(--muted); font-weight: 400; }}
  .cd {{ font-size: 11px; color: var(--muted); }}
  .cbar {{ height: 5px; background: #eee; border-radius: 3px; overflow: hidden; margin-top: 6px; }}
  .cbar-fill {{ height: 100%; background: #94a3b8; border-radius: 3px; }}

  .kpis {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
  .kpi {{ background: #fafbfc; border: 1px solid var(--border); border-radius: 10px;
          padding: 12px; }}
  .kpi .k {{ color: var(--muted); font-size: 12px; }}
  .kpi .v {{ font-size: 22px; font-weight: 700; margin-top: 2px; }}
  .kpi .d {{ font-size: 11px; color: var(--muted); }}

  .chart {{ width: 100%; height: 340px; }}
  .two {{ display: grid; grid-template-columns: 1.7fr 1fr; gap: 16px; margin-top: 16px; }}
  @media (max-width: 900px) {{ .two {{ grid-template-columns: 1fr; }} }}

  .note {{ background: #fff8e6; border-left: 4px solid #ef9f27; padding: 10px 14px;
           border-radius: 8px; font-size: 13px; margin-top: 12px; }}
  .footer {{ text-align: center; color: var(--muted); font-size: 12px; margin-top: 20px; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="head">
    <h1>创业板位置驾驶舱</h1>
    <div class="sub">创业板指(399006) ｜ 数据截至 {last_date} ｜ 当前 {r['latest']:.2f}（当日 {cur.get('change_pct') or 0:.1f}%）</div>
  </div>

  <div class="top">
    <div class="card gauge-box">
      <h2>位置温度</h2>
      <div id="gauge"></div>
      <div class="gauge-label"><span class="big" style="color:{color}">{_temp_label(temp)}</span></div>
      <div class="pos-rec">建议仓位 <span class="pct" style="color:{color}">{r['suggest_pos']*100:.0f}%</span></div>
    </div>

    <div class="card">
      <h2>位置三要素</h2>
      <div class="comps">{comp_html}</div>
    </div>

    <div class="card">
      <h2>关键指标</h2>
      <div class="kpis">
        <div class="kpi"><div class="k">PE-TTM</div>
          <div class="v">{r['pe_ttm']:.2f}</div>
          <div class="d">历史分位 {_pct(r['pe_pct'])}</div></div>
        <div class="kpi"><div class="k">PB</div>
          <div class="v">{r['pb']:.2f}</div>
          <div class="d">历史分位 {_pct(r['pb_pct'])}</div></div>
        <div class="kpi"><div class="k">MA60</div>
          <div class="v">{r['ma60']:.0f}</div>
          <div class="d">{'站上' if r['above_ma60'] else '跌破'}</div></div>
        <div class="kpi"><div class="k">MA250</div>
          <div class="v">{r['ma250']:.0f}</div>
          <div class="d">{'站上' if r['above_ma250'] else '跌破'}</div></div>
      </div>
    </div>
  </div>

  <div class="two">
    <div class="card">
      <h2>近5年点位走势</h2>
      <div id="price" class="chart"></div>
    </div>
    <div class="card">
      <h2>信号与建议</h2>
      <div style="font-size:14px; line-height:1.9">
        <p style="font-size:18px; font-weight:700; color:{color}">{r['signal']}</p>
        <p style="margin-top:8px">{r['advice']}</p>
      </div>
      <div class="note">⚠️ 位置分位低 ≠ 不会继续跌。估值分位（PE {_pct(r['pe_pct'])}）远低于价格分位，
      说明「跌了且真的变便宜」，是相对可靠的低位信号；但仍需结合基本面与政策判断。</div>
    </div>
  </div>

  <div class="footer">本驾驶舱基于公开数据量化生成，仅供研究参考，不构成投资建议。</div>
</div>

<script>
  (function(){{
    var temp = {temp if temp is not None else 'null'};
    var chart = echarts.init(document.getElementById('gauge'));
    chart.setOption({{
      series: [{{
        type: 'gauge', startAngle: 210, endAngle: -30, min: 0, max: 100,
        axisLine: {{ lineStyle: {{ width: 16, color: [[0.2,'#1d9e75'],[0.4,'#e8d21d'],[0.6,'#f09a3a'],[0.8,'#e8752a'],[1,'#e24b4a']] }} }},
        pointer: {{ width: 5, length: '62%' }},
        axisTick: {{ show: false }}, splitLine: {{ length: 12, lineStyle: {{ color: '#999', width: 2 }} }},
        axisLabel: {{ distance: 20, fontSize: 10 }},
        detail: {{ formatter: '{{value|.1f}}', fontSize: 30, offsetCenter: [0, '55%'], color: '{color}' }},
        data: [{{ value: temp, name: '位置温度' }}]
      }}]
    }});
  }})();

  (function(){{
    var chart = echarts.init(document.getElementById('price'));
    var d = {json.dumps(series['dates'])};
    var c = {json.dumps([round(float(x),1) for x in series['closes']])};
    chart.setOption({{
      tooltip: {{ trigger: 'axis' }},
      grid: {{ left: 50, right: 20, top: 20, bottom: 30 }},
      xAxis: {{ type: 'category', data: d, boundaryGap: false }},
      yAxis: {{ type: 'value', scale: true }},
      dataZoom: [{{ type: 'inside' }}, {{ type: 'slider', height: 18, bottom: 2 }}],
      series: [{{
        name: '创业板指', type: 'line', data: c, showSymbol: false,
        lineStyle: {{ width: 1.5, color: '#e24b4a' }},
        areaStyle: {{ opacity: 0.06, color: '#e24b4a' }}
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
    path = os.path.join(REPORT_DIR, f"创业板位置驾驶舱_{date_str}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"驾驶舱已生成：{path}")


if __name__ == "__main__":
    main()
