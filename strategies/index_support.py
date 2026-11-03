"""宽基指数支撑位分析（通用版）。

复用 index_risk.fetcher 的指数日 K 采集，对任意宽基指数做技术面支撑/压力位量化，
输出终端报告 + HTML 可视化。

支持指数（代码）：
    399006 创业板指 / 000688 科创50 / 399001 深证成指
    000300 沪深300 / 000016 上证50 / 000905 中证500

要点：
    - 同时识别「下方支撑位」与「上方压力位（均线系统）」。
    - 支撑位来源：历史显著低点（近 3 年分段低点）、斐波那契回撤、整数关口、
      成交密集区(VWAP)。
    - 均线系统在当前价上方时自动归为「压力位」而非支撑。

用法：
    .venv/Scripts/python.exe index_support.py 000688   # 科创50
    .venv/Scripts/python.exe index_support.py 399006   # 创业板指

仅基于公开数据的量化参考，不构成投资建议。
"""

from __future__ import annotations

import datetime
import html
import sys
from typing import Dict, List

from index_risk.fetcher import fetch_kline, INDEX_CONFIG, FetchError


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _ma(closes: List[float], n: int) -> float:
    if len(closes) < n:
        return closes[-1] if closes else 0.0
    return sum(closes[-n:]) / n


def _round_price(p: float) -> float:
    return round(p, 0)


def _cluster(levels: List[float], tol: float = 0.015) -> List[float]:
    s = sorted(set(levels))
    out = []
    for p in s:
        if out and abs(p - out[-1]) / out[-1] < tol:
            continue
        out.append(p)
    return out


def _find_local_lows(values: List[float], half_win: int = 15) -> List[float]:
    n = len(values)
    out = []
    for i in range(half_win, n - half_win):
        seg = values[i - half_win:i + half_win + 1]
        if values[i] == min(seg):
            out.append(values[i])
    return out


# ---------------------------------------------------------------------------
# 支撑/压力位分析
# ---------------------------------------------------------------------------
def analyze(klines: List[Dict]) -> Dict:
    closes = [k["close"] for k in klines]
    lows = [k["low"] for k in klines]
    highs = [k["high"] for k in klines]
    cur = closes[-1]

    supports: List[Dict] = []
    resistances: List[Dict] = []

    # ---- 1. 均线系统 ----
    ma_map = [
        ("MA20", _ma(closes, 20), "短线多空分界，破位后转压力"),
        ("MA60", _ma(closes, 60), "中期趋势线"),
        ("MA120", _ma(closes, 120), "半年线，趋势强弱分界"),
        ("MA250", _ma(closes, 250), "年线，牛熊分界线"),
    ]
    for name, ma, reason in ma_map:
        if ma <= 0:
            continue
        if ma < cur:
            strength = "强" if name in ("MA120", "MA250") else "中"
            supports.append({
                "price": _round_price(ma), "label": name,
                "strength": strength, "kind": "均线支撑", "reason": reason,
            })
        else:
            resistances.append({
                "price": _round_price(ma), "label": name,
                "strength": "压力", "kind": "均线压力", "reason": reason,
            })

    # ---- 2. 历史显著低点 ----
    local_lows = _find_local_lows(lows)
    below = _cluster([p for p in local_lows if p < cur])
    for p in below[-3:]:
        supports.append({
            "price": p, "label": f"前低 {p:.0f}",
            "strength": "中", "kind": "历史前低",
            "reason": "历史阶段性低点，回踩易获承接",
        })

    # ---- 3. 斐波那契回撤（近 3 年高低点） ----
    h = max(highs)
    l = min(lows)
    for name, ratio in [("0.382", 0.382), ("0.5", 0.5), ("0.618", 0.618)]:
        lvl = h - (h - l) * ratio
        if lvl < cur:
            supports.append({
                "price": _round_price(lvl), "label": f"斐波那契 {ratio}",
                "strength": "中", "kind": "斐波那契",
                "reason": "经典回撤位，技术派集中参考",
            })

    # ---- 4. 成交密集区 VWAP ----
    seg = klines[-250:] if len(klines) >= 250 else klines
    total_v = sum(k["volume"] for k in seg) or 1.0
    vwap = sum(k["close"] * k["volume"] for k in seg) / total_v
    if vwap < cur:
        supports.append({
            "price": _round_price(vwap), "label": "成交密集区(VWAP)",
            "strength": "强", "kind": "筹码密集",
            "reason": "近一年成交量加权均价，主力持仓成本密集区",
        })
    else:
        resistances.append({
            "price": _round_price(vwap), "label": "成交密集区(VWAP)",
            "strength": "压力", "kind": "筹码密集",
            "reason": "近一年成交密集成本在上方，构成套牢盘压力",
        })

    # ---- 5. 整数关口 ----
    step = 100
    base = int(cur // step) * step
    for i in range(1, 4):
        gate = base - i * step
        if gate > 0:
            supports.append({
                "price": float(gate), "label": f"整数关口 {gate}",
                "strength": "弱", "kind": "心理关口",
                "reason": "心理整数关口，情绪支撑非硬支撑",
            })

    def dedup(items: List[Dict]) -> List[Dict]:
        out: List[Dict] = []
        for c in items:
            if any(abs(c["price"] - m["price"]) / m["price"] < 0.012 for m in out):
                continue
            out.append(c)
        return out

    supports = dedup(sorted(supports, key=lambda x: -x["price"]))
    resistances = dedup(sorted(resistances, key=lambda x: x["price"]))

    return {
        "close": cur,
        "supports": supports,
        "resistances": resistances,
        "high_3y": h,
        "low_3y": l,
    }


# ---------------------------------------------------------------------------
# 终端报告
# ---------------------------------------------------------------------------
def print_report(name: str, res: Dict):
    W = 82
    cur = res["close"]
    print("=" * W)
    print(f"{name}支撑位分析（技术面）")
    print(f"数据时间: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
    print("=" * W)
    print(f"\n当前点位: {cur:.2f}")
    print(f"近3年区间: 最高 {res['high_3y']:.0f} / 最低 {res['low_3y']:.0f}")
    dd = (cur - res["high_3y"]) / res["high_3y"]
    print(f"距3年高点回撤: {dd:.1%}")

    print("\n【下方支撑位】（由近到远）")
    print(f"  {'支撑位':>10}  {'强度':<4}  {'类型':<10}  说明")
    print("  " + "-" * 70)
    if res["supports"]:
        for s in res["supports"]:
            mark = {"强": "🟢", "中": "🟡", "弱": "⚪"}[s["strength"]]
            dist = (s["price"] - cur) / cur
            print(f"  {s['price']:>10.0f}  {mark}{s['strength']:<3}  {s['kind']:<10}  {s['label']}  距现价 {dist:+.1%}")
            print(f"  {'':>10}  {'':<4}  {'':<10}  └ {s['reason']}")
    else:
        print("  （无）当前已处于历史低位，下方无有效技术支撑")

    print("\n【上方压力位】（均线系统，由近到远）")
    print(f"  {'压力位':>10}  {'类型':<10}  说明")
    print("  " + "-" * 70)
    for r in res["resistances"]:
        dist = (r["price"] - cur) / cur
        print(f"  {r['price']:>10.0f}  {r['kind']:<10}  {r['label']}  距现价 {dist:+.1%}")
        print(f"  {'':>10}  {'':<10}  └ {r['reason']}")

    print("\n" + "-" * W)
    print("【结论】")
    strong = [s for s in res["supports"] if s["strength"] == "强"]
    mid = [s for s in res["supports"] if s["strength"] == "中"]
    if strong:
        strong_desc = "、".join(f"{s['label']}({s['price']:.0f})" for s in strong)
        print(f"  最硬支撑：{strong_desc}")
    if mid:
        mid_desc = "、".join(f"{s['label']}({s['price']:.0f})" for s in mid)
        print(f"  次级支撑：{mid_desc}")
    if res["resistances"]:
        r0 = res["resistances"][0]
        print(f"  最近压力：{r0['label']}({r0['price']:.0f})，上方套牢盘较重")
    print("\n⚠️ 支撑位是概率参考而非铁底，跌破需及时止损；本分析不构成投资建议。")


# ---------------------------------------------------------------------------
# HTML 报告
# ---------------------------------------------------------------------------
def render_html(name: str, res: Dict, out_path: str):
    cur = res["close"]
    rows_s = ""
    for s in res["supports"]:
        mark = {"强": "🟢", "中": "🟡", "弱": "⚪"}[s["strength"]]
        dist = (s["price"] - cur) / cur
        rows_s += (
            f"<tr><td>{s['price']:.0f}</td><td>{mark} {s['strength']}</td>"
            f"<td>{s['kind']}</td><td>{s['label']}</td>"
            f"<td style='color:#d33'>{dist:+.1%}</td><td>{html.escape(s['reason'])}</td></tr>"
        )
    rows_r = ""
    for r in res["resistances"]:
        dist = (r["price"] - cur) / cur
        rows_r += (
            f"<tr><td>{r['price']:.0f}</td><td>{r['kind']}</td>"
            f"<td>{r['label']}</td><td style='color:#0a7'>{dist:+.1%}</td>"
            f"<td>{html.escape(r['reason'])}</td></tr>"
        )
    dd = (cur - res["high_3y"]) / res["high_3y"]

    doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name}支撑位分析</title>
<style>
body{{font-family:-apple-system,'Microsoft YaHei',sans-serif;margin:0;background:#f5f6f8;color:#222;}}
.wrap{{max-width:960px;margin:0 auto;padding:24px;}}
h1{{font-size:22px;margin:0 0 4px;}}
.sub{{color:#888;font-size:13px;margin-bottom:20px;}}
.card{{background:#fff;border-radius:10px;padding:20px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,.06);}}
.card h2{{font-size:16px;margin:0 0 12px;border-left:4px solid #3b82f6;padding-left:8px;}}
table{{width:100%;border-collapse:collapse;font-size:14px;}}
th,td{{padding:8px 10px;text-align:left;border-bottom:1px solid #eee;}}
th{{background:#fafafa;color:#666;font-weight:600;}}
.price{{font-size:34px;font-weight:700;color:#1a56db;}}
.stat{{display:flex;gap:24px;flex-wrap:wrap;margin-top:12px;}}
.stat div{{font-size:13px;color:#666;}}
.stat b{{color:#222;font-size:16px;}}
.note{{font-size:12px;color:#999;margin-top:16px;line-height:1.6;}}
</style></head><body><div class="wrap">
<h1>{name}支撑位分析（技术面）</h1>
<div class="sub">数据时间 {datetime.datetime.now():%Y-%m-%d %H:%M:%S} · 仅供研究参考，不构成投资建议</div>
<div class="card">
<div class="price">{cur:.2f}</div>
<div class="sub">当前点位</div>
<div class="stat">
<div>近3年最高 <b>{res['high_3y']:.0f}</b></div>
<div>近3年最低 <b>{res['low_3y']:.0f}</b></div>
<div>距高点回撤 <b style="color:#d33">{dd:.1%}</b></div>
</div>
</div>
<div class="card"><h2>下方支撑位</h2>
<table><thead><tr><th>点位</th><th>强度</th><th>类型</th><th>名称</th><th>距现价</th><th>说明</th></tr></thead>
<tbody>{rows_s or '<tr><td colspan="6">当前已处历史低位，下方无有效技术支撑</td></tr>'}</tbody></table>
</div>
<div class="card"><h2>上方压力位（均线系统）</h2>
<table><thead><tr><th>点位</th><th>类型</th><th>名称</th><th>距现价</th><th>说明</th></tr></thead>
<tbody>{rows_r or '<tr><td colspan="5">无</td></tr>'}</tbody></table>
</div>
<div class="note">⚠️ 支撑位是概率参考而非铁底，跌破需及时止损。本分析基于公开数据的量化参考，不构成投资建议。数据来源：新浪财经。</div>
</div></body></html>"""

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(doc)
    return out_path


def main():
    code = sys.argv[1] if len(sys.argv) > 1 else "000688"
    if code not in INDEX_CONFIG:
        print(f"❌ 未知指数代码 {code}，支持：{', '.join(INDEX_CONFIG)}")
        return
    name = INDEX_CONFIG[code]["name"]

    print(f"正在采集 {name} 日 K（新浪财经）...")
    try:
        klines = fetch_kline(code, days=800)
        if not klines:
            print("❌ 未获取到日 K 数据")
            return
    except FetchError as e:
        print(f"❌ 数据采集失败: {e}")
        return

    res = analyze(klines)
    print_report(name, res)

    import os
    os.makedirs("../reports", exist_ok=True)
    out = f"reports/{name}支撑位_{datetime.date.today():%Y-%m-%d}.html"
    render_html(name, res, out)
    print(f"\n📄 HTML 报告已生成: {out}")


if __name__ == "__main__":
    main()
