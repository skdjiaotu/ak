"""每日市场体检报告 —— HTML 可视化渲染。

遵循 A 股惯例：上涨/危险用红色，下跌/安全用绿色。
"""

from __future__ import annotations


def _fmt(v, nd=1, suffix=""):
    if v is None:
        return "N/A"
    return f"{v:,.{nd}f}{suffix}"


def _pct(v, nd=1):
    if v is None:
        return "N/A"
    return f"{v:.{nd}f}%"


def _signal_class(signal: str) -> str:
    if "红" in signal:
        return "sig-red"
    if "黄" in signal:
        return "sig-yellow"
    return "sig-green"


def render_html(report, overall) -> str:
    r = report
    ff = r["fund_flow"]

    # 指数表格行
    idx_rows = ""
    for i in r["indexes"]:
        cls = _signal_class(i["signal"])
        idx_rows += f"""
        <tr>
          <td class="name">{i['name']}</td>
          <td>{_fmt(i['pe_ttm'], 1)}</td>
          <td>{_pct(i['pe_percentile'])}</td>
          <td>{_pct(i['pb_percentile'])}</td>
          <td>{_pct(i['drawdown'])}</td>
          <td>{_fmt(i['score'], 0)}</td>
          <td><span class="sig {cls}">{i['signal']}</span></td>
        </tr>"""

    # 恐慌指数行
    vix_rows = ""
    for v in r["vix"]:
        vol = v["vol"] * 100 if v["vol"] else None
        lvl_cls = "lvl-red" if "极度恐慌" in v["level"] else (
            "lvl-orange" if "恐慌" in v["level"] else (
                "lvl-yellow" if "中性" in v["level"] else "lvl-green"))
        vix_rows += f"""
        <tr>
          <td class="name">{v['name']}</td>
          <td>{_pct(vol)}</td>
          <td>{_pct(v['vol_percentile'])}</td>
          <td><span class="sig {lvl_cls}">{v['level']}</span></td>
        </tr>"""

    # 综合判定 class
    ov_cls = _signal_class(overall["overall"])

    notes_html = ""
    for n in overall["notes"]:
        notes_html += f"<li>{n}</li>"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>每日市场体检报告 {r['fetched_at'][:10]}</title>
<style>
  :root {{
    --bg: #f5f6f8; --card: #ffffff; --text: #1a1a1a; --muted: #666;
    --red: #e24b4a; --green: #1d9e75; --yellow: #ba7517;
    --border: #e5e7eb;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
         background: var(--bg); color: var(--text); line-height: 1.6; padding: 24px; }}
  .wrap {{ max-width: 960px; margin: 0 auto; }}
  h1 {{ font-size: 22px; font-weight: 600; }}
  .sub {{ color: var(--muted); font-size: 13px; margin-bottom: 20px; }}
  .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px;
           padding: 20px; margin-bottom: 20px; }}
  h2 {{ font-size: 16px; font-weight: 600; margin-bottom: 12px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th, td {{ padding: 8px 10px; text-align: right; border-bottom: 1px solid var(--border); }}
  th {{ color: var(--muted); font-weight: 500; font-size: 13px; }}
  td.name, th.name {{ text-align: left; }}
  .sig {{ display: inline-block; padding: 2px 10px; border-radius: 20px; font-size: 13px; white-space: nowrap; }}
  .sig-red {{ background: #fcebeb; color: #a32d2d; }}
  .sig-green {{ background: #e1f5ee; color: #0f6e56; }}
  .sig-yellow {{ background: #faeeda; color: #854f0b; }}
  .lvl-red {{ background: #fcebeb; color: #a32d2d; }}
  .lvl-orange {{ background: #faeeda; color: #993c1d; }}
  .lvl-yellow {{ background: #f1efe8; color: #5f5e5a; }}
  .lvl-green {{ background: #e1f5ee; color: #0f6e56; }}
  .overall {{ font-size: 18px; font-weight: 600; margin-bottom: 12px; }}
  .overall .sig {{ font-size: 16px; padding: 4px 16px; }}
  ul {{ padding-left: 20px; }}
  li {{ margin: 6px 0; font-size: 14px; }}
  .kv {{ display: flex; flex-wrap: wrap; gap: 16px; font-size: 14px; }}
  .kv div {{ min-width: 180px; }}
  .kv .k {{ color: var(--muted); font-size: 13px; }}
  .warn {{ background: #fff8e6; border-left: 4px solid #ef9f27; padding: 12px 16px;
           border-radius: 8px; font-size: 14px; margin-top: 12px; }}
  .footer {{ text-align: center; color: var(--muted); font-size: 12px; margin-top: 24px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>📊 A 股每日市场体检报告</h1>
  <div class="sub">数据时间：{r['fetched_at']} ｜ 四维交叉验证：估值 · 技术 · 资金 · 情绪</div>

  <div class="card">
    <div class="overall">综合判定：<span class="sig {ov_cls}">{overall['overall']}</span></div>
    <div class="kv">
      <div><span class="k">红灯</span><br><b>{overall['red']}</b> 个</div>
      <div><span class="k">黄灯</span><br><b>{overall['yellow']}</b> 个</div>
      <div><span class="k">绿灯</span><br><b>{overall['green']}</b> 个</div>
    </div>
    <ul style="margin-top:12px">{notes_html}</ul>
  </div>

  <div class="card">
    <h2>① 宽基指数估值 · 技术 · 危险度</h2>
    <table>
      <thead><tr>
        <th class="name">指数</th><th>PE-TTM</th><th>PE分位</th><th>PB分位</th><th>距前高回撤</th><th>危险度</th><th>信号</th>
      </tr></thead>
      <tbody>{idx_rows}</tbody>
    </table>
    <div class="warn">⚠️ 危险度 0=安全 100=危险；PE/PB 分位来自蛋卷基金完整历史；回撤为距 250 日高点。</div>
  </div>

  <div class="card">
    <h2>② 资金面 —— 两融 + 北向（穿透官方假象）</h2>
    <div class="kv">
      <div><span class="k">融资余额</span><br><b>{_fmt(ff['margin_balance']/1e8 if ff['margin_balance'] else None, 0)}</b> 亿元</div>
      <div><span class="k">融资余额 20 日变化</span><br><b>{_pct(ff['margin_balance_20d'])}</b></div>
      <div><span class="k">融资余额/流通市值</span><br><b>{_fmt(ff['margin_ratio'])}</b>%</div>
    </div>
    <ul style="margin-top:12px">
      <li>杠杆资金判定：<b>{ff['margin_trend']}</b></li>
      <li>情绪状态：<b>{ff['margin_emotion']}</b></li>
      <li>北向净买入：已于 <b>{ff['north_nan_date']}</b> 停止披露（最后披露 {ff['north_last_date']}）</li>
      <li>停更前外资态度：<b>{ff['north_signal']}</b></li>
    </ul>
  </div>

  <div class="card">
    <h2>③ 恐慌指数（20 日年化波动率）</h2>
    <table>
      <thead><tr><th class="name">指数</th><th>当前波动率</th><th>历史分位</th><th>恐慌等级</th></tr></thead>
      <tbody>{vix_rows}</tbody>
    </table>
  </div>

  <div class="footer">本报告基于公开数据量化生成，仅供研究参考，不构成投资建议。</div>
</div>
</body>
</html>"""
