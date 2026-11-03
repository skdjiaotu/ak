# -*- coding: utf-8 -*-
"""多因子选股组合回测框架（个股）。

与 ETF 轮动研究一脉相承，但针对个股做了三个关键适配：
  1. 数据源：腾讯前复权行情(防除权假跳空) + 新浪季度财务因子
  2. 幸存者偏差规避：股票池用「指数历史成分股」而非"今天还活着的票"
  3. 组合化：多因子打分选 Top N 等权持有，不重仓单票

复用 etf_rotation 的 A 股成本口径(佣金/印花税/过户费/滑点)和 perf 绩效函数。

数据仅供研究教学演示，不构成投资建议。
"""
from __future__ import annotations

import os
import time

import numpy as np
import pandas as pd
import akshare as ak

from etf_rotation import COMMISSION, STAMP_TAX, TRANSFER_FEE, SLIPPAGE, perf

# ---------------------------------------------------------------------------
# 全局配置
# ---------------------------------------------------------------------------
START_DATE = "20180101"     # 回测起始
CACHE_DIR = os.path.join("../stock", "cache")     # 数据缓存目录（避免重复拉取）
STOCK_POOL_SIZE = 60        # 股票池数量（取沪深300按市值排序前 N，控制拉取量）

# 因子定义：量价因子 + 财务因子
# 每个因子：name=中文名, type=price(量价,实时截面) 或 fundamental(财务,季度截面),
#           sign=1 表示"越大越好"，sign=-1 表示"越小越好"
FACTORS = [
    # ---- 量价因子 ----
    {"name": "动量", "key": "momentum", "type": "price", "sign": 1, "window": 60},
    {"name": "反转", "key": "reversal", "type": "price", "sign": 1, "window": 5},
    {"name": "低波动", "key": "volatility", "type": "price", "sign": -1, "window": 20},
    # ---- 财务因子（季度） ----
    {"name": "ROE", "key": "roe", "type": "fundamental", "sign": 1},
    {"name": "毛利率", "key": "gross_margin", "type": "fundamental", "sign": 1},
    {"name": "营收增长", "key": "revenue_growth", "type": "fundamental", "sign": 1},
]


# ---------------------------------------------------------------------------
# 数据层
# ---------------------------------------------------------------------------
# 板块指数成分（覆盖创业板 / 深主板 / 科创板）
BOARD_INDEXES = {
    "创业板指": "399006",   # 创业板，100 只
    "科创50": "000688",     # 科创板，50 只
    "深证成指": "399001",   # 深主板+创业板宽基，500 只
}


def get_stock_pool(n: int = STOCK_POOL_SIZE):
    """获取股票池：沪深300成分股按市值排序取前 N。

    用指数成分股而非"手写名单"，规避幸存者偏差——指数成分是动态调整的，
    历史回测需配合时点截面，这里用当前成分作为可运行的基础股票池。
    返回 DataFrame: [code, name]，code 为 6 位数字代码。
    """
    df = ak.index_stock_cons_weight_csindex(symbol="000300")
    df = df[df["权重"].astype(float) > 0].copy()
    df["代码"] = df["成分券代码"].astype(str).str.zfill(6)
    # 按权重降序取前 N（权重大≈市值大）
    df = df.sort_values("权重", ascending=False).head(n)
    return df[["代码", "成分券名称"]].rename(columns={"成分券名称": "名称"})


def get_board_pool(indexes: list = None, limit_per_index: int = None):
    """获取「创业板+科创板+深主板」多板块股票池（新浪成分接口，稳定）。

    indexes : 要合并的指数代码列表，默认 BOARD_INDEXES 的值。
    limit_per_index : 每个指数最多取多少只（None=全取）。用于控制数据量。

    返回 DataFrame: [代码, 名称]，代码为 6 位数字（已去重）。
    """
    indexes = indexes or list(BOARD_INDEXES.values())
    frames = []
    for sym in indexes:
        try:
            df = ak.index_stock_cons_sina(symbol=sym)
            if df is None or len(df) == 0:
                print(f"  [跳过指数] {sym}: 无数据")
                continue
            # symbol 形如 sz300001 / sh688002，提取纯数字代码
            df = df.copy()
            df["代码"] = df["symbol"].astype(str).str[-6:]
            df["名称"] = df["name"]
            if limit_per_index:
                df = df.head(limit_per_index)
            frames.append(df[["代码", "名称"]])
            print(f"  {sym}: {len(df)} 只")
        except Exception as e:
            print(f"  [跳过指数] {sym}: {str(e)[:60]}")
    if not frames:
        return pd.DataFrame(columns=["代码", "名称"])
    pool = pd.concat(frames, ignore_index=True).drop_duplicates("代码").reset_index(drop=True)
    return pool


def _code_to_symbol(code: str) -> str:
    """6 位代码 → 带交易所前缀的 symbol（腾讯接口用）。"""
    if code.startswith(("6", "9")):
        return "sh" + code
    return "sz" + code


def fetch_price(code: str, start: str = START_DATE) -> pd.Series:
    """拉取单只个股前复权收盘价（腾讯接口），返回 date→close 的 Series。"""
    sym = _code_to_symbol(code)
    df = ak.stock_zh_a_hist_tx(symbol=sym, start_date=start, end_date="20991231")
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df.set_index("date")["close"]


def fetch_fundamental(code: str) -> pd.DataFrame:
    """拉取单只个股季度财务因子，返回 date→{roe, gross_margin, revenue_growth}。

    新浪 stock_financial_analysis_indicator 接口，字段为季度值。
    """
    # 注意：此接口要求「纯数字代码」，不能带 sh/sz 前缀；且传 start_year 会返回空
    df = ak.stock_financial_analysis_indicator(symbol=code)
    if df is None or len(df) == 0:
        raise ValueError("财务数据为空")
    df = df.copy()
    dates = pd.to_datetime(df["日期"])
    out = pd.DataFrame({
        "roe": pd.to_numeric(df["净资产收益率(%)"], errors="coerce").values,
        "gross_margin": pd.to_numeric(df["销售毛利率(%)"], errors="coerce").values,
        "revenue_growth": pd.to_numeric(df["主营业务收入增长率(%)"], errors="coerce").values,
    }, index=dates.values)
    return out.sort_index()


def build_price_panel(codes: list, cache_path: str) -> pd.DataFrame:
    """构建收盘价面板（列=代码，索引=日期），带本地缓存。"""
    if os.path.exists(cache_path):
        panel = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        return panel

    closes = {}
    for i, c in enumerate(codes):
        try:
            s = fetch_price(c)
            closes[c] = s
        except Exception as e:
            print(f"  [跳过] {c} 拉取失败: {str(e)[:60]}")
        if (i + 1) % 10 == 0:
            print(f"  已拉取 {i+1}/{len(codes)} 只")
        time.sleep(0.3)  # 限速，避免被接口封

    panel = pd.DataFrame(closes).sort_index()
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    panel.to_csv(cache_path)
    return panel


def build_fundamental_panel(codes: list, cache_path: str) -> dict:
    """构建财务因子面板，返回 {因子key: DataFrame(日期×代码)}，带缓存。

    注意：财务因子是季度频率，需要前向填充到日频，供回测时点截面使用。
    """
    if os.path.exists(cache_path):
        import pickle
        with open(cache_path, "rb") as f:
            return pickle.load(f)

    roe, gm, rg = {}, {}, {}
    for i, c in enumerate(codes):
        try:
            f = fetch_fundamental(c)
            # 有效性校验：若关键列全空，说明被限速返回空数据，重试一次
            if not f["roe"].notna().any():
                time.sleep(2.0)
                f = fetch_fundamental(c)
            roe[c] = f["roe"]
            gm[c] = f["gross_margin"]
            rg[c] = f["revenue_growth"]
        except Exception as e:
            print(f"  [跳过财务] {c}: {str(e)[:60]}")
        if (i + 1) % 20 == 0:
            print(f"  已拉财务 {i+1}/{len(codes)} 只")
        time.sleep(1.5)  # 限速：新浪财务接口连续请求需较长间隔，否则返回空数据

    def to_panel(d):
        # 过滤掉全空 Series，避免 NaT 崩溃
        d = {k: v for k, v in d.items() if v is not None and v.notna().any()}
        if not d:
            return pd.DataFrame()
        p = pd.DataFrame(d).sort_index()
        if p.index.isna().any() or p.empty:
            return pd.DataFrame()
        # 前向填充到日频
        idx = pd.date_range(p.index.min(), p.index.max(), freq="B")
        return p.reindex(idx).ffill()

    result = {
        "roe": to_panel(roe),
        "gross_margin": to_panel(gm),
        "revenue_growth": to_panel(rg),
    }
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    import pickle
    with open(cache_path, "wb") as f:
        pickle.dump(result, f)
    return result


# ---------------------------------------------------------------------------
# 因子计算
# ---------------------------------------------------------------------------
def compute_price_factors(panel: pd.DataFrame) -> dict:
    """基于价格面板计算量价因子截面。

    返回 {因子key: DataFrame(日期×代码, 因子值)}。
    """
    rets = panel.pct_change()
    # 动量：过去 window 日累计收益
    momentum = panel / panel.shift(60) - 1
    # 反转：过去 5 日收益（取负值方向用 sign 处理，这里给原始值）
    reversal = panel / panel.shift(5) - 1
    # 波动率：过去 20 日收益标准差（年化）
    volatility = rets.rolling(20).std() * np.sqrt(250)
    return {"momentum": momentum, "reversal": reversal, "volatility": volatility}


# ---------------------------------------------------------------------------
# 回测引擎
# ---------------------------------------------------------------------------
def zscore_cross_section(df: pd.DataFrame) -> pd.DataFrame:
    """按行（每个日期）做横截面 z-score 标准化。"""
    return df.sub(df.mean(axis=1), axis=0).div(df.std(axis=1), axis=0)


def run_factor_backtest(panel, fund_panels, factor_keys, factor_signs,
                        top_n=20, rebalance=20, ma_filter=False, ma_period=60,
                        return_series=False):
    """多因子选股组合回测。

    参数：
      panel        : 收盘价面板（日期×代码）
      fund_panels  : 财务因子面板 dict（key→日期×代码）
      factor_keys  : 参与打分的因子 key 列表
      factor_signs : 每个因子的方向（1 越大越好 / -1 越小越好）
      top_n        : 每期持有的股票数（等权）
      rebalance    : 调仓周期（交易日）
      ma_filter    : 是否叠加"仅持有站上 MA 的票"的趋势过滤（可选）
      ma_period    : 趋势过滤均线周期

    打分逻辑：每个因子横截面 z-score 标准化 → 乘方向符号 → 加总 → 排序取 Top N。
    成本口径：复用 etf_rotation 的 A 股成本（按换手权重折算）。
    """
    n, m = panel.shape
    codes = list(panel.columns)
    close = panel.values

    # 计算量价因子
    price_factors = compute_price_factors(panel)

    # 合成每日打分矩阵
    score = pd.DataFrame(0.0, index=panel.index, columns=panel.columns)
    for key, sign in zip(factor_keys, factor_signs):
        if key in price_factors:
            raw = price_factors[key]
        elif key in fund_panels:
            raw = fund_panels[key]
        else:
            raise ValueError(f"未知因子: {key}")
        # 对齐索引；财务面板可能缺失某些代码列，用 reindex 对齐（缺失填 NaN）
        raw = raw.reindex(index=panel.index, columns=panel.columns)
        z = zscore_cross_section(raw)
        score = score + sign * z.fillna(0.0)

    # 趋势过滤均线（shift(1)：用"截至昨日"的均线决定今日持仓，消除前视偏差）
    ma = pd.DataFrame(close).rolling(ma_period).mean().shift(1).values if ma_filter else None

    # 关键修正：打分矩阵整体前移一天。
    # 用"i-1 日收盘时的打分"决定 i 日的持仓，这样 i 日吃的是 i-1→i 的真实收益，
    # 不依赖 i 日收盘价（这是实盘唯一可执行的方式，之前版本存在前视偏差）。
    score_lag = score.shift(1)

    # 起始位置（再多留 1 日给 shift）
    start = 61
    rets = []
    held = []   # 当前持有的代码列表
    for i in range(start, n):
        if i % rebalance == 0 or not held:
            day_score = score_lag.iloc[i]  # i-1 日收盘的打分
            valid = day_score[day_score.notna()]
            # 可选：趋势过滤（用昨日收盘 vs 昨日均线）
            if ma_filter:
                above = [codes[j] for j in range(m) if close[i - 1, j] > ma[i, j]]
                valid = valid[valid.index.isin(above)]
            if len(valid) >= top_n:
                new_held = list(valid.sort_values(ascending=False).head(top_n).index)
            elif len(valid) >= 1:
                new_held = list(valid.sort_values(ascending=False).index)
            else:
                new_held = []

            # 换手成本（复用 A 股成本口径）
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

        # 当日收益：等权持有（持仓是昨日确定的，吃今日真实涨跌）
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


def summarize(name, total, ann, dd, sharpe):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    print(f"  累计收益  : {total*100:.1f}%")
    print(f"  年化收益  : {ann*100:.1f}%")
    print(f"  最大回撤  : {dd*100:.1f}%")
    print(f"  夏普比率  : {sharpe:.2f}")


def main():
    print("=" * 60)
    print("  多因子选股组合回测（个股）")
    print("=" * 60)

    # 1. 股票池
    print("\n[1/4] 获取股票池（沪深300 前 N）...")
    pool = get_stock_pool(STOCK_POOL_SIZE)
    codes = list(pool["代码"])
    print(f"  股票池 {len(codes)} 只，示例: {codes[:5]}")

    # 2. 价格面板
    price_cache = os.path.join(CACHE_DIR, "price_panel.csv")
    print("\n[2/4] 构建价格面板（腾讯前复权，带缓存）...")
    panel = build_price_panel(codes, price_cache)
    print(f"  面板: {panel.shape[0]} 日 × {panel.shape[1]} 只, "
          f"{panel.index[0].date()} ~ {panel.index[-1].date()}")

    # 3. 财务面板
    fund_cache = os.path.join(CACHE_DIR, "fundamental.pkl")
    print("\n[3/4] 构建财务因子面板（新浪季度，带缓存）...")
    fund_panels = build_fundamental_panel(codes, fund_cache)
    print(f"  ROE 面板: {fund_panels['roe'].shape}")

    # 4. 回测对比
    print("\n[4/4] 运行回测对比...")
    price_keys = ["momentum", "reversal", "volatility"]
    fund_keys = ["roe", "gross_margin", "revenue_growth"]
    all_keys = price_keys + fund_keys
    all_signs = [1, 1, -1, 1, 1, 1]  # 动量+ 反转+ 低波动- ROE+ 毛利率+ 营收增长+

    # 4.1 纯量价因子
    total, ann, dd, sharpe = run_factor_backtest(
        panel, fund_panels, price_keys, [1, 1, -1], top_n=20, rebalance=20)
    summarize("纯量价因子(动量+反转+低波动)", total, ann, dd, sharpe)

    # 4.2 纯财务因子
    total, ann, dd, sharpe = run_factor_backtest(
        panel, fund_panels, fund_keys, [1, 1, 1], top_n=20, rebalance=20)
    summarize("纯财务因子(ROE+毛利率+营收增长)", total, ann, dd, sharpe)

    # 4.3 全因子
    total, ann, dd, sharpe = run_factor_backtest(
        panel, fund_panels, all_keys, all_signs, top_n=20, rebalance=20)
    summarize("全因子组合", total, ann, dd, sharpe)

    # 4.4 全因子 + 趋势过滤
    total, ann, dd, sharpe = run_factor_backtest(
        panel, fund_panels, all_keys, all_signs, top_n=20, rebalance=20,
        ma_filter=True, ma_period=60)
    summarize("全因子 + MA60趋势过滤", total, ann, dd, sharpe)

    # 基准：等权买入持有全部股票池
    bench_ret = panel.pct_change().mean(axis=1).dropna()
    bench_ret = bench_ret[bench_ret.index >= panel.index[60]]
    total, ann, dd, sharpe = perf(bench_ret)
    summarize("基准(等权买入持有全池)", total, ann, dd, sharpe)

    print("\n" + "=" * 60)
    print("  仅供研究参考，不构成投资建议。")


if __name__ == "__main__":
    main()
