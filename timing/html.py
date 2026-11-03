"""买方择时模型 —— HTML 可视化渲染。"""

from __future__ import annotations

import html


def render_html(report, timing) -> str:
    sig = timing["score"]
    comp = timing["components"]
    weights = timing["weights"]

    # 四维打分卡片
    cards = ""
    for k in ["估值", "技术", "资金", "情绪"]:
        c = comp[k]
        w = weights[k]
        cards += f"""
        <div class="dim">
          <div class="dim-head"><span>{k}</span><span class="w">权重 {w:.0%}</span></div>
          <div class="dim-score">{c['score']:.0f}<span>/100</span></div>
          <div class="dim-bar"><div class="dim-fill" style="width:{c['score']}%"></div></div>
          <div class="dim-note">{html.escape(c['note'])}</div>
        </div>"""

    # 回测表
    bt_rows = ""
    for r in report["backtests"]:
        delta = r["strategy_ret"] - r["hold_ret"]
        delta_str = f"{delta*100:+.1f}pp"
        bt_rows += f"""
        <tr>
          <td>{r['name']}</td>
          <td style="color:#c0392b">{r['strategy_ret']*100:.1f}%</td>
          <td>{r['hold_ret']*100:.1f}%</td>
          <td style="color:#27ae60">{r['strategy_mdd']*100:.1f}%</td>
          <td>{r['hold_mdd']*100:.1f}%</td>
          <td>{r['holding_ratio']*100:.0f}%</td>
          <td>{delta_str}</td>
        </tr>"""

    # 分数颜色
    if sig >= 75:
        score_color = "#27ae60"
    elif sig >= 60:
        score_color = "#2ecc71"
    elif sig >= 45:
        score_color = "#f39c12"
    elif sig >= 30:
        score_color = "#e67e22"
    else:
        score_color = "#c0392b"

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>A股市场择时模型</title>
<style>
body{{font-family:-apple-system,'Microsoft YaHei',sans-serif;margin:0;background:#f5f6f8;color:#222;}}
.wrap{{max-width:960px;margin:0 auto;padding:24px;}}
h1{{font-size:22px;margin:0 0 4px;}}
.sub{{color:#888;font-size:13px;margin-bottom:20px;}}
.card{{background:#fff;border-radius:12px;padding:20px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,.06);}}
.card h2{{font-size:16px;margin:0 0 14px;border-left:4px solid #3b82f6;padding-left:8px;}}
.score{{display:flex;align-items:baseline;gap:16px;}}
.score-num{{font-size:48px;font-weight:700;color:{score_color};}}
.score-sig{{font-size:18px;font-weight:500;}}
.advice{{margin-top:8px;font-size:15px;color:#444;}}
.warn{{margin-top:8px;font-size:13px;color:#c0392b;}}
.dims{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;}}
.dim{{background:#fafafa;border-radius:10px;padding:14px;}}
.dim-head{{display:flex;justify-content:space-between;font-size:14px;font-weight:500;}}
.dim-head .w{{color:#999;font-weight:400;font-size:12px;}}
.dim-score{{font-size:28px;font-weight:700;margin:6px 0;}}
.dim-score span{{font-size:13px;font-weight:400;color:#999;}}
.dim-bar{{height:6px;background:#eee;border-radius:3px;overflow:hidden;}}
.dim-fill{{height:100%;background:#3b82f6;border-radius:3px;}}
.dim-note{{font-size:12px;color:#666;margin-top:8px;line-height:1.5;}}
table{{width:100%;border-collapse:collapse;font-size:14px;}}
th,td{{padding:8px 10px;text-align:left;border-bottom:1px solid #eee;}}
th{{background:#fafafa;color:#666;font-weight:600;}}
.note{{font-size:12px;color:#999;margin-top:16px;line-height:1.7;}}
.concl{{background:#fff8e1;border-radius:10px;padding:14px;font-size:13px;color:#795548;line-height:1.7;}}
@media(max-width:720px){{.dims{{grid-template-columns:repeat(2,1fr);}}}}
</style></head><body><div class="wrap">
<h1>A 股市场择时模型（买方视角）</h1>
<div class="sub">数据时间 {report['fetched_at']} · 仅供研究参考，不构成投资建议</div>

<div class="card">
  <div class="score">
    <div class="score-num">{sig:.1f}</div>
    <div>
      <div class="score-sig">市场机会分 / 100</div>
      <div class="advice">建议：{html.escape(timing['advice'])}</div>
      {f'<div class="warn">⚠️ 杠杆资金在撤离，即使估值偏低也需控制抄底节奏</div>' if timing['deleveraging'] else ''}
    </div>
  </div>
</div>

<div class="card"><h2>四维打分</h2>
  <div class="dims">{cards}</div>
</div>

<div class="card"><h2>回测验证（近3年 · 估值+趋势双确认）</h2>
  <table><thead><tr>
    <th>指数</th><th>择时收益</th><th>持有收益</th><th>择时回撤</th><th>持有回撤</th><th>持仓占比</th><th>超额</th>
  </tr></thead><tbody>{bt_rows}</tbody></table>
  <div class="concl">
    近3年属单边下跌市，择时策略收益跑输满仓持有，但<b>最大回撤显著收窄</b>——
    这证明择时的价值在于「控回撤、活下来」，而非「赚更多」。单边熊市中应降低仓位预期，
    等待右侧趋势确认（如站上 MA60）后再加仓，避免越跌越买接飞刀。
  </div>
</div>

<div class="note">⚠️ 本模型基于公开数据量化（蛋卷基金 / 新浪财经 / 东方财富 / 乐咕乐股），仅供研究参考，不构成投资建议。</div>
</div></body></html>"""


def signal_name(score: float) -> str:
    if score >= 75:
        return "机会区"
    elif score >= 60:
        return "偏机会"
    elif score >= 45:
        return "中性区"
    elif score >= 30:
        return "谨慎区"
    else:
        return "危险区"
