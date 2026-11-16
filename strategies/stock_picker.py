# -*- coding: utf-8 -*-
"""多因子选股策略 —— 综合打分挑个股（可回测 + 可出今日名单）。

设计定位：
  在项目现有「量价+财务」因子选股框架(stock_factor_backtest.py)之上，
  补齐三大缺口，做成一个可实战、可复现、可解释的完整策略：

  1. 因子体系扩展：量价(动量/反转/低波动) + 财务(ROE/毛利率/营收增长) + 估值(PE/PB 分位)
  2. 行业中性化：因子在行业内标准化，避免「金融天然高杠杆」之类行业偏差污染打分
  3. 前视偏差消除：打分用「昨收」决定「今日」持仓，均线同样用昨日值

  同时提供「今日选股名单」输出：代码/名称/行业/综合分/核心亮点，供人工复核。

用法：
  .venv/Scripts/python.exe stock_picker.py                 # 回测对比 + 今日名单
  .venv/Scripts/python.exe stock_picker.py --top 15 --rebalance 20
  .venv/Scripts/python.exe stock_picker.py --pick-only      # 只出今日名单，不跑回测

数据仅供研究教学演示，不构成投资建议。
"""
from __future__ import annotations

import argparse
import os
import pickle
import time

import numpy as np
import pandas as pd
import akshare as ak

from etf_rotation import COMMISSION, STAMP_TAX, TRANSFER_FEE, SLIPPAGE, perf

# ---------------------------------------------------------------------------
# 全局配置
# ---------------------------------------------------------------------------
START_DATE = "20180101"
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", "stock", "cache")

# 因子定义（含估值因子）
FACTORS = [
    # ---- 量价因子 ----
    {"name": "动量",      "key": "momentum",      "type": "price",  "sign": 1,  "window": 60},
    {"name": "反转",      "key": "reversal",      "type": "price",  "sign": 1,  "window": 5},
    {"name": "低波动",    "key": "volatility",    "type": "price",  "sign": -1, "window": 20},
    # ---- 财务因子（季度，越大越好）----
    {"name": "ROE",       "key": "roe",            "type": "fundamental", "sign": 1},
    {"name": "毛利率",    "key": "gross_margin",   "type": "fundamental", "sign": 1},
    {"name": "营收增长",  "key": "revenue_growth", "type": "fundamental", "sign": 1},
    # ---- 估值因子（越小越好 = 越便宜）----
    {"name": "PE分位",    "key": "pe_pct",         "type": "valuation", "sign": -1},
    {"name": "PB分位",    "key": "pb_pct",         "type": "valuation", "sign": -1},
]

# 行业中性化：以下行业在选股时按行业内部打分，避免行业间因子不可比
INDUSTRY_NEUTRAL = True


# ---------------------------------------------------------------------------
# 数据层
# ---------------------------------------------------------------------------
def _code_to_symbol(code: str) -> str:
    return "sh" + code if code.startswith(("6", "9")) else "sz" + code


# 指数代码 → 中文名（用于股票池合并）
INDEX_POOL = {
    "000300": "沪深300",   # 大盘蓝筹，300 只
    "000905": "中证500",   # 中盘成长，500 只
}


def get_stock_pool(n: int = 100, indexes: list = None) -> pd.DataFrame:
    """股票池：默认「沪深300 + 中证500」（中证800范围）按权重取前 N。

    indexes : 要合并的指数代码列表，默认 ["000300", "000905"]。
              传入 ["000300"] 则退化为纯沪深300。
    返回 [代码, 名称, 所属指数]（跨指数去重，保留权重更大的所属指数）。
    """
    indexes = indexes or list(INDEX_POOL.keys())
    frames = []
    for sym in indexes:
        try:
            df = ak.index_stock_cons_weight_csindex(symbol=sym)
            df = df[df["权重"].astype(float) > 0].copy()
            df["代码"] = df["成分券代码"].astype(str).str.zfill(6)
            df["名称"] = df["成分券名称"]
            df["所属指数"] = INDEX_POOL.get(sym, sym)
            df["_w"] = df["权重"].astype(float)
            frames.append(df[["代码", "名称", "所属指数", "_w"]])
        except Exception as e:
            print(f"  [跳过指数] {sym}: {str(e)[:60]}")
    if not frames:
        return pd.DataFrame(columns=["代码", "名称", "所属指数"])

    pool = pd.concat(frames, ignore_index=True)
    # 跨指数去重：同一代码保留权重更大的一行（优先沪深300 还是中证500 由权重决定）
    pool = pool.sort_values("_w", ascending=False).drop_duplicates("代码").reset_index(drop=True)
    # 按权重降序取前 N
    pool = pool.sort_values("_w", ascending=False).head(n).reset_index(drop=True)
    return pool[["代码", "名称", "所属指数"]]


def get_industry_map(codes: list) -> dict:
    """代码 → 行业（用于行业中性化与名单展示）。

    优先用东财行业板块成分（stock_board_industry_cons_em）反查；
    该接口走东财 push2，限流时会失败——此时优雅降级为全"未知"，
    行业中性化自动退化为全局标准化（不阻塞主流程）。
    """
    mapping = {}
    try:
        boards = ak.stock_board_industry_name_em()
        board_names = boards["板块名称"].tolist()
    except Exception:
        board_names = []

    code_set = set(codes)
    for bname in board_names:
        try:
            cons = ak.stock_board_industry_cons_em(symbol=bname)
            for code in cons["代码"].astype(str).str.zfill(6).tolist():
                if code in code_set and code not in mapping:
                    mapping[code] = bname
        except Exception:
            continue
        time.sleep(0.2)

    for c in codes:
        mapping.setdefault(c, "未知")
    return mapping


def fetch_price(code: str, start: str = START_DATE) -> pd.Series:
    df = ak.stock_zh_a_hist_tx(symbol=_code_to_symbol(code),
                               start_date=start, end_date="20991231")
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df.set_index("date")["close"]


def fetch_fundamental(code: str) -> pd.DataFrame:
    df = ak.stock_financial_analysis_indicator(symbol=code)
    if df is None or len(df) == 0:
        raise ValueError("财务数据为空")
    dates = pd.to_datetime(df["日期"])
    out = pd.DataFrame({
        "roe": pd.to_numeric(df["净资产收益率(%)"], errors="coerce").values,
        "gross_margin": pd.to_numeric(df["销售毛利率(%)"], errors="coerce").values,
        "revenue_growth": pd.to_numeric(df["主营业务收入增长率(%)"], errors="coerce").values,
    }, index=dates.values)
    return out.sort_index()


def fetch_valuation(code: str) -> pd.DataFrame:
    """PE/PB 估值历史分位（东财估值接口，日频），返回 date→{pe_pct, pb_pct}。

    分位为 0~100（数值越大越贵）。用「当前估值在自身历史中的分位」，
    比绝对 PE 更稳健，天然适应不同行业的估值中枢。
    """
    df = ak.stock_value_em(symbol=code)
    if df is None or len(df) == 0:
        raise ValueError("估值数据为空")
    df = df.copy()
    date = pd.to_datetime(df["数据日期"])
    pe = pd.to_numeric(df["PE(TTM)"], errors="coerce")
    pb = pd.to_numeric(df["市净率"], errors="coerce")

    def _expanding_pct_rank(s: pd.Series, idx: pd.Index) -> pd.Series:
        """稳健的 expanding 分位：前向填充 NaN 后，用 (累计小于等于当前值的个数)/累计样本数。

        规避 pandas expanding().rank(pct=True) 对 NaN 的传染问题。
        idx 为目标 datetime 索引（与 s 等长，用于最终赋值）。
        """
        s = s.ffill().reset_index(drop=True)
        out = np.full(len(s), np.nan)
        for i in range(len(s)):
            if i == 0 or pd.isna(s.iloc[i]):
                continue
            window = s.iloc[: i + 1].dropna()
            if len(window) < 5:  # 样本太少分位无意义
                continue
            out[i] = (window <= s.iloc[i]).sum() / len(window) * 100
        return pd.Series(out, index=idx)

    pe_rank = _expanding_pct_rank(pe, date)
    pb_rank = _expanding_pct_rank(pb, date)
    return pd.DataFrame({"pe_pct": pe_rank, "pb_pct": pb_rank}).sort_index()


def build_price_panel(codes, cache_path):
    """价格面板（增量缓存）：缓存缺失的代码才拉取，合并后覆盖保存。"""
    cached = pd.DataFrame()
    if os.path.exists(cache_path):
        cached = pd.read_csv(cache_path, index_col=0, parse_dates=True)

    missing = [c for c in codes if c not in cached.columns]
    if not missing:
        return cached[codes]

    closes = {}
    for i, c in enumerate(missing):
        try:
            closes[c] = fetch_price(c)
        except Exception as e:
            print(f"  [跳过] {c} 拉取失败: {str(e)[:50]}")
        if (i + 1) % 10 == 0:
            print(f"  已拉取 {i+1}/{len(missing)}")
        time.sleep(0.3)

    panel = pd.concat([cached, pd.DataFrame(closes)], axis=1).sort_index()
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    panel.to_csv(cache_path)
    # 只返回实际拉取到的列（缺失代码由后续 reindex 兜底为 NaN）
    available = [c for c in codes if c in panel.columns]
    return panel[available]


def build_fundamental_panel(codes, cache_path):
    """财务因子面板（增量缓存）：缓存缺失的代码才拉取。

    缓存结构约定：{因子key: {代码: Series}}（与 stock_factor_backtest 的 DataFrame 缓存
    不兼容，故用独立文件名，避免读到旧格式导致 KeyError）。
    """
    cached = {}
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            cached = pickle.load(f)

    # 缓存结构校验：若缓存是旧 DataFrame 格式（历史遗留），丢弃重建
    def _is_valid(d):
        return isinstance(d, dict) and all(isinstance(v, dict) for v in d.values())

    if not _is_valid(cached):
        cached = {}

    def to_panel(d):
        d = {k: v for k, v in d.items() if v is not None and v.notna().any()}
        if not d:
            return pd.DataFrame()
        p = pd.DataFrame(d).sort_index()
        if p.index.isna().any() or p.empty:
            return pd.DataFrame()
        idx = pd.date_range(p.index.min(), p.index.max(), freq="B")
        return p.reindex(idx).ffill()

    missing = [c for c in codes if c not in cached.get("roe", {})]
    if missing:
        roe, gm, rg = {}, {}, {}
        for i, c in enumerate(missing):
            try:
                f = fetch_fundamental(c)
                if not f["roe"].notna().any():
                    time.sleep(2.0)
                    f = fetch_fundamental(c)
                roe[c], gm[c], rg[c] = f["roe"], f["gross_margin"], f["revenue_growth"]
            except Exception as e:
                print(f"  [跳过财务] {c}: {str(e)[:50]}")
            if (i + 1) % 20 == 0:
                print(f"  已拉财务 {i+1}/{len(missing)}")
            time.sleep(1.5)

        # 合并缓存与新增
        for k, new_d in (("roe", roe), ("gross_margin", gm), ("revenue_growth", rg)):
            merged = dict(cached.get(k, {}))
            merged.update(new_d)
            cached[k] = merged

        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "wb") as f:
            pickle.dump(cached, f)

    # 统一返回 DataFrame 格式（无论是否命中缓存）
    return {"roe": to_panel(cached.get("roe", {})),
            "gross_margin": to_panel(cached.get("gross_margin", {})),
            "revenue_growth": to_panel(cached.get("revenue_growth", {}))}


def build_valuation_panel(codes, cache_path):
    """估值因子面板（增量缓存）：缓存缺失的代码才拉取。

    缓存结构约定：{因子key: {代码: Series}}，返回 DataFrame（日期×代码）。
    """
    cached = {}
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            cached = pickle.load(f)

    def _is_valid(d):
        return isinstance(d, dict) and all(isinstance(v, dict) for v in d.values())

    if not _is_valid(cached):
        cached = {}

    missing = [c for c in codes if c not in cached.get("pe_pct", {})]
    if missing:
        pe = dict(cached.get("pe_pct", {}))
        pb = dict(cached.get("pb_pct", {}))
        for i, c in enumerate(missing):
            try:
                v = fetch_valuation(c)
                pe[c], pb[c] = v["pe_pct"], v["pb_pct"]
            except Exception as e:
                print(f"  [跳过估值] {c}: {str(e)[:50]}")
            if (i + 1) % 20 == 0:
                print(f"  已拉估值 {i+1}/{len(missing)}")
            time.sleep(0.4)
        cached = {"pe_pct": pe, "pb_pct": pb}
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "wb") as f:
            pickle.dump(cached, f)

    return {"pe_pct": _to_panel(cached.get("pe_pct", {})),
            "pb_pct": _to_panel(cached.get("pb_pct", {}))}


def _to_panel(d):
    d = {k: v for k, v in d.items() if v is not None and v.notna().any()}
    if not d:
        return pd.DataFrame()
    p = pd.DataFrame(d).sort_index()
    if p.index.isna().any() or p.empty:
        return pd.DataFrame()
    idx = pd.date_range(p.index.min(), p.index.max(), freq="B")
    return p.reindex(idx).ffill()


# ---------------------------------------------------------------------------
# 因子计算
# ---------------------------------------------------------------------------
def compute_price_factors(panel):
    rets = panel.pct_change()
    momentum = panel / panel.shift(60) - 1
    reversal = panel / panel.shift(5) - 1
    volatility = rets.rolling(20).std() * np.sqrt(250)
    return {"momentum": momentum, "reversal": reversal, "volatility": volatility}


def zscore(df):
    return df.sub(df.mean(axis=1), axis=0).div(df.std(axis=1), axis=0)


def zscore_neutral(df, industry_map):
    """行业中性化 z-score：每行(每日)在每个行业内标准化，再合并。"""
    df = df.copy()
    code_to_ind = {c: industry_map.get(c, "未知") for c in df.columns}
    out = pd.DataFrame(index=df.index, columns=df.columns, dtype=float)
    for ind in set(code_to_ind.values()):
        cols = [c for c in df.columns if code_to_ind[c] == ind]
        if len(cols) < 2:
            out[cols] = 0.0
            continue
        sub = df[cols]
        z = sub.sub(sub.mean(axis=1), axis=0).div(sub.std(axis=1), axis=0)
        out[cols] = z
    return out


# ---------------------------------------------------------------------------
# 打分与选股
# ---------------------------------------------------------------------------
def build_score_matrix(panel, fund_panels, val_panels, factor_keys, factor_signs,
                       industry_map=None):
    """合成每日综合打分矩阵（已做标准化，可加行业中性化）。"""
    price_factors = compute_price_factors(panel)
    score = pd.DataFrame(0.0, index=panel.index, columns=panel.columns)
    for key, sign in zip(factor_keys, factor_signs):
        if key in price_factors:
            raw = price_factors[key]
        elif key in fund_panels:
            raw = fund_panels[key]
        elif key in val_panels:
            raw = val_panels[key]
        else:
            raise ValueError(f"未知因子: {key}")
        raw = raw.reindex(index=panel.index, columns=panel.columns)
        if INDUSTRY_NEUTRAL and industry_map and key != "volatility":
            z = zscore_neutral(raw, industry_map)
        else:
            z = zscore(raw)
        score = score + sign * z.fillna(0.0)
    return score


def select_stocks(score_row, top_n, ma_series=None, held=None):
    """从单日打分选出 Top N，返回代码列表。ma_series 为昨日均线(可选趋势过滤)。"""
    valid = score_row[score_row.notna()]
    if ma_series is not None:
        above = [c for c in valid.index
                 if c in ma_series.index and ma_series[c] is not None
                 and valid[c] == valid[c]]  # 占位，趋势过滤在回测里用 close/ma 判断
    return list(valid.sort_values(ascending=False).head(top_n).index)


# ---------------------------------------------------------------------------
# 回测引擎
# ---------------------------------------------------------------------------
def run_backtest(panel, score, top_n=15, rebalance=20, ma_filter=False,
                 ma_period=60, return_series=False):
    """多因子打分选股回测。

    score : 综合打分矩阵（日期×代码），本函数内部做 shift(1) 消除前视偏差。
    """
    n, m = panel.shape
    codes = list(panel.columns)
    close = panel.values
    score_lag = score.shift(1)

    ma = pd.DataFrame(close).rolling(ma_period).mean().shift(1).values if ma_filter else None
    start = max(61, ma_period + 1)

    held = []
    rets = []
    for i in range(start, n):
        if i % rebalance == 0 or not held:
            day_score = score_lag.iloc[i]
            valid = day_score[day_score.notna()]
            if ma_filter:
                above = [codes[j] for j in range(m) if close[i - 1, j] > ma[i, j]]
                valid = valid[valid.index.isin(above)]
            if len(valid) >= top_n:
                new_held = list(valid.sort_values(ascending=False).head(top_n).index)
            elif len(valid) >= 1:
                new_held = list(valid.sort_values(ascending=False).index)
            else:
                new_held = []

            tc = 0.0
            if new_held != held:
                sell_names = [c for c in held if c not in new_held]
                if sell_names:
                    sell_w = len(sell_names) / len(held) if held else 0.0
                    tc += sell_w * (COMMISSION + STAMP_TAX + TRANSFER_FEE + SLIPPAGE)
                buy_names = [c for c in new_held if c not in held]
                if buy_names:
                    buy_w = len(buy_names) / len(new_held) if new_held else 0.0
                    tc += buy_w * (COMMISSION + TRANSFER_FEE + SLIPPAGE)
            held = new_held
        else:
            tc = 0.0

        if held:
            ret = np.mean([close[i, codes.index(c)] / close[i - 1, codes.index(c)] - 1
                           for c in held])
        else:
            ret = 0.0
        rets.append(ret - tc)

    rets = pd.Series(rets, index=panel.index[start:])
    if return_series:
        return rets
    return perf(rets)


# ---------------------------------------------------------------------------
# 今日选股名单
# ---------------------------------------------------------------------------
def pick_today(panel, score, pool, industry_map, top_n=15):
    """基于最新打分，输出今日推荐名单。"""
    last_score = score.iloc[-1]
    valid = last_score[last_score.notna()]
    top = valid.sort_values(ascending=False).head(top_n)

    name_map = dict(zip(pool["代码"], pool["名称"]))
    index_map = dict(zip(pool["代码"], pool["所属指数"])) if "所属指数" in pool.columns else {}
    rows = []
    for c, s in top.items():
        rows.append({
            "代码": c,
            "名称": name_map.get(c, ""),
            "指数": index_map.get(c, ""),
            "行业": industry_map.get(c, "未知"),
            "综合分": round(float(s), 2),
            "最新价": round(float(panel[c].iloc[-1]), 2),
        })
    df = pd.DataFrame(rows)
    df = df.sort_values("综合分", ascending=False).reset_index(drop=True)
    df.index = df.index + 1
    return df


def _summarize(name, total, ann, dd, sharpe):
    print(f"  {name:<24} 累计{total*100:>8.1f}%  年化{ann*100:>7.1f}%  "
          f"回撤{dd*100:>6.1f}%  夏普{sharpe:>5.2f}")


def main():
    ap = argparse.ArgumentParser(description="多因子选股策略（回测 + 今日名单）")
    ap.add_argument("--top", type=int, default=20, help="每期持有股票数")
    ap.add_argument("--rebalance", type=int, default=5, help="调仓周期(交易日)")
    ap.add_argument("--pool", type=int, default=150, help="股票池数量(沪深300+中证500合并后按权重取前N)")
    ap.add_argument("--index", type=str, default="000300,000905",
                    help="股票池指数代码(逗号分隔)，如 000300,000905 或 000300")
    ap.add_argument("--ma", type=int, default=60, help="趋势过滤均线周期")
    ap.add_argument("--pick-only", action="store_true", help="只出今日名单，跳过回测")
    args = ap.parse_args()

    indexes = [s.strip() for s in args.index.split(",") if s.strip()]

    print("=" * 72)
    print("  多因子选股策略 —— 综合打分挑个股")
    print("=" * 72)

    # 1. 股票池
    idx_names = " + ".join(INDEX_POOL.get(i, i) for i in indexes)
    print(f"\n[1/5] 获取股票池（{idx_names}，前 {args.pool}）...")
    pool = get_stock_pool(args.pool, indexes)
    codes = list(pool["代码"])
    print(f"  股票池 {len(codes)} 只")
    if "所属指数" in pool.columns:
        print("  指数分布:", pool["所属指数"].value_counts().to_dict())

    # 行业映射
    print("  获取行业映射...")
    ind_cache = os.path.join(CACHE_DIR, "industry_map.pkl")
    industry_map = {}
    if os.path.exists(ind_cache):
        with open(ind_cache, "rb") as f:
            industry_map = pickle.load(f)
    # 缓存覆盖不全则补拉（仅拉缺失代码）
    missing_ind = [c for c in codes if c not in industry_map]
    if missing_ind:
        print(f"  补拉行业映射 {len(missing_ind)} 只...")
        new_map = get_industry_map(missing_ind)
        industry_map.update(new_map)
        with open(ind_cache, "wb") as f:
            pickle.dump(industry_map, f)

    # 2. 价格面板
    price_cache = os.path.join(CACHE_DIR, "price_panel.csv")
    print("\n[2/5] 构建价格面板（腾讯前复权，带缓存）...")
    panel = build_price_panel(codes, price_cache)
    print(f"  面板: {panel.shape[0]} 日 × {panel.shape[1]} 只, "
          f"{panel.index[0].date()} ~ {panel.index[-1].date()}")
    # 对齐：以价格面板实际拉到的列为准（个别票拉取失败会缺失）
    codes = list(panel.columns)
    pool = pool[pool["代码"].isin(codes)].reset_index(drop=True)

    # 数据清洗：前向填充停牌/滞后的价格（避免 NaN 传染到打分与回测）
    panel = panel.ffill()
    # 截断到所有票都有数据的共同起点之后（保留足够回测长度即可）
    panel = panel.dropna(how="all")

    # 3. 财务面板
    fund_cache = os.path.join(CACHE_DIR, "fundamental_stockpicker.pkl")
    print("\n[3/5] 构建财务因子面板（新浪季度，带缓存）...")
    fund_panels = build_fundamental_panel(codes, fund_cache)

    # 4. 估值面板
    val_cache = os.path.join(CACHE_DIR, "valuation_stockpicker.pkl")
    print("\n[4/5] 构建估值因子面板（东财历史分位，带缓存）...")
    val_panels = build_valuation_panel(codes, val_cache)

    # 5. 打分矩阵
    print("\n[5/5] 合成综合打分矩阵...")
    factor_keys = [f["key"] for f in FACTORS]
    factor_signs = [f["sign"] for f in FACTORS]
    score = build_score_matrix(panel, fund_panels, val_panels,
                               factor_keys, factor_signs, industry_map)

    # ---- 今日选股名单 ----
    print("\n" + "=" * 72)
    print(f"  今日选股名单（Top {args.top}，按综合分降序）")
    print("=" * 72)
    today = pick_today(panel, score, pool, industry_map, args.top)
    if today.empty:
        print("  （无有效打分，可能数据未就绪）")
    else:
        print(today.to_string(index=True))

    if args.pick_only:
        print("\n  仅供研究参考，不构成投资建议。")
        return

    # ---- 回测对比 ----
    print("\n" + "=" * 72)
    print("  回测绩效对比（2018 至今，含 A 股交易成本）")
    print("=" * 72)
    price_keys = ["momentum", "reversal", "volatility"]
    fund_keys = ["roe", "gross_margin", "revenue_growth"]
    val_keys = ["pe_pct", "pb_pct"]
    all_keys = price_keys + fund_keys + val_keys
    all_signs = [1, 1, -1, 1, 1, 1, -1, -1]

    total, ann, dd, sharpe = run_backtest(
        panel, build_score_matrix(panel, fund_panels, val_panels,
                                  price_keys, [1, 1, -1], industry_map),
        top_n=args.top, rebalance=args.rebalance)
    _summarize("纯量价因子", total, ann, dd, sharpe)

    total, ann, dd, sharpe = run_backtest(
        panel, build_score_matrix(panel, fund_panels, val_panels,
                                  fund_keys + val_keys, [1, 1, 1, -1, -1], industry_map),
        top_n=args.top, rebalance=args.rebalance)
    _summarize("财务+估值因子", total, ann, dd, sharpe)

    total, ann, dd, sharpe = run_backtest(panel, score, top_n=args.top,
                                          rebalance=args.rebalance)
    _summarize("全因子组合", total, ann, dd, sharpe)

    total, ann, dd, sharpe = run_backtest(panel, score, top_n=args.top,
                                          rebalance=args.rebalance,
                                          ma_filter=True, ma_period=args.ma)
    _summarize(f"全因子+MA{args.ma}过滤", total, ann, dd, sharpe)

    bench = panel.pct_change().mean(axis=1).dropna()
    bench = bench[bench.index >= panel.index[60]]
    total, ann, dd, sharpe = perf(bench)
    _summarize("基准(等权持有全池)", total, ann, dd, sharpe)

    print("\n  仅供研究参考，不构成投资建议。")


if __name__ == "__main__":
    main()
