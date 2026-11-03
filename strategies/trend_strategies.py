# -*- coding: utf-8 -*-
"""AKQuant 趋势交易策略库（可导入模块）。

把策略类与公共工具抽取到此模块，供以下入口复用：
  - trend_strategy.py        单标的回测入口
  - trend_optimize.py        参数网格优化入口（Windows 多进程要求策略类可导入）
  - trend_portfolio.py       多标的组合回测入口

注意：Windows 下 run_grid_search 多进程用 spawn 启动，策略类必须定义在
可导入模块（本模块），不能定义在 __main__ 中。

数据仅供研究教学演示，不构成投资建议。
"""

from __future__ import annotations

import numpy as np

from akquant import Strategy, IntParam, FloatParam, SMA


# ---------------------------------------------------------------------------
# A 股交易成本配置（回测统一口径）
# ---------------------------------------------------------------------------
# 使用 AKQuant 内置 A 股券商模板，完整覆盖：
#   佣金（双边，万3，最低 5 元）、印花税（卖出单边 0.05%，2023-08-28 起现行）、
#   过户费（双边，万0.1）、滑点（0.02%）、手数 100 股、T+1。
# 说明：若要回测 2023-08-28 之前的数据，印花税应按 0.1% 计（旧税率），
#       需显式传 stamp_tax_rate=0.001 覆盖。此处采用现行税率 0.05%。
A_SHARE_BROKER_PROFILE = "cn_stock_miniqmt"
# 备选：cn_stock_t1_low_fee（低佣金场景）/ cn_stock_sim_high_slippage（保守高滑点）

# 纯 pandas 回测（etf_rotation / timing）手写的 A 股成本参数，与上面对齐：
#   佣金双边 0.025%（万2.5，取行业常见值）、印花税卖出单边 0.05%、
#   过户费双边 0.001%（万0.1）、滑点双边 0.1%（含盘口价差，偏保守）。
A_SHARE_COMMISSION = 0.00025      # 佣金率（双边）
A_SHARE_STAMP_TAX = 0.0005        # 印花税率（卖出单边）
A_SHARE_TRANSFER_FEE = 0.00001    # 过户费率（双边）
A_SHARE_SLIPPAGE = 0.001          # 滑点（双边，比例）


# ---------------------------------------------------------------------------
# 数据准备
# ---------------------------------------------------------------------------
# ETF 池（代码 → 中文名）。ETF 走 fund_etf_hist_sina 接口，与指数/个股数据源不同。
ETF_POOL = {
    # 海外 / 红利 ETF
    "sh513500": "标普500ETF",
    "sh512890": "红利低波ETF",
    "sh513520": "日经ETF",
    "sh513030": "德国ETF",
    # 六大宽基指数对应的 ETF（可直接买卖，替代指数代码）
    "sh510300": "沪深300ETF",
    "sz159915": "创业板ETF",
    "sh510500": "中证500ETF",
    "sh510050": "上证50ETF",
    "sh588000": "科创50ETF",
    "sz159903": "深证成指ETF",
}

# 指数代码前缀补全规则（纯数字代码 → 带交易所前缀）
_INDEX_PREFIX = {"sh": ("000", "600", "601", "603", "688"), "sz": ("399",)}


def _resolve_symbol(symbol: str) -> tuple[str, bool]:
    """解析标的代码，返回 (带前缀代码, 是否为ETF)。

    - ETF：带 sh/sz 前缀且 5 开头（如 sh513500）→ 走 ETF 接口
    - 个股：带 sh/sz 前缀且非 5 开头 → 走个股接口
    - 指数：纯数字 → 自动补前缀，走指数接口
    """
    if symbol in ETF_POOL:
        return symbol, True
    if symbol.isdigit():
        code = symbol
        prefix = "sh" if code.startswith(_INDEX_PREFIX["sh"]) else "sz"
        return prefix + code, False
    return symbol, False


def fetch_data(symbol: str, start: str, end: str):
    """用 AKShare 拉取日线数据，转为 AKQuant 需要的 DataFrame。

    symbol 支持三种形式：
      - ETF：sh513500 / sh512890（带前缀、5 开头，或已在 ETF_POOL 中）
      - 个股：sh600000 / sz000858（带交易所前缀）
      - 指数：000300 / 399006（纯数字，自动补前缀）
    """
    import akshare as ak

    symbol, is_etf = _resolve_symbol(symbol)

    if is_etf:
        # ETF 用新浪基金接口（前复权），字段为 date/open/high/low/close/volume
        df = ak.fund_etf_hist_sina(symbol=symbol)
        df = df.sort_values("date").reset_index(drop=True)
        df["date"] = df["date"].astype(str)
        df = df[df["date"] >= start].reset_index(drop=True)
        if end:
            df = df[df["date"] <= end].reset_index(drop=True)
        df["symbol"] = symbol
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        df = df[["date", "open", "high", "low", "close", "volume", "symbol"]]
        return df, symbol

    # 指数 / 个股用 stock_zh_a_daily 接口
    df = ak.stock_zh_a_daily(symbol=symbol, start_date=start, end_date=end)

    df = df.rename(columns={
        "date": "date", "open": "open", "high": "high",
        "low": "low", "close": "close", "volume": "volume",
    })
    df["date"] = df["date"].astype(str)
    df["symbol"] = symbol
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df = df[["date", "open", "high", "low", "close", "volume", "symbol"]]
    df = df.sort_values("date").reset_index(drop=True)
    return df, symbol


def fetch_multi_data(symbols: list, start: str, end: str):
    """拉取多标的日线数据并拼接成一个 DataFrame（供组合回测）。"""
    import pandas as pd
    frames = []
    resolved = []
    for s in symbols:
        df, sym = fetch_data(s, start, end)
        frames.append(df)
        resolved.append(sym)
    return pd.concat(frames, ignore_index=True), resolved


# ---------------------------------------------------------------------------
# 策略 1：双均线交叉
# ---------------------------------------------------------------------------
class DualMACrossStrategy(Strategy):
    """双均线交叉趋势策略。

    金叉（快线上穿慢线）买入，死叉（快线下穿慢线）清仓。
    """

    fast_period = IntParam(30, ge=2, le=250, title="快线周期")
    slow_period = IntParam(60, ge=3, le=500, title="慢线周期")

    def on_start(self):
        self.set_history_depth(self.params.slow_period + 5)

    def _calc_ma(self, symbol, period):
        hist = self.get_history(count=period, symbol=symbol, field="close")
        if hist is None or len(hist) < period:
            return None
        return float(np.mean(hist))

    def on_bar(self, bar):
        fast = self._calc_ma(bar.symbol, self.params.fast_period)
        slow = self._calc_ma(bar.symbol, self.params.slow_period)
        if fast is None or slow is None:
            return
        pos = self.get_position(bar.symbol)
        if fast > slow and pos <= 0:
            self.buy(symbol=bar.symbol, quantity=100)
        elif fast < slow and pos > 0:
            self.close_position(symbol=bar.symbol)


# ---------------------------------------------------------------------------
# 策略 2：单均线趋势过滤（基础版）
# ---------------------------------------------------------------------------
class MA60TrendStrategy(Strategy):
    """单均线趋势过滤策略。

    收盘价站上 MA60 → 持有（买入）；收盘价跌破 MA60 → 空仓（清仓）。
    """

    ma_period = IntParam(60, ge=5, le=250, title="均线周期")

    def on_start(self):
        self.set_history_depth(self.params.ma_period + 5)

    def _calc_ma(self, symbol):
        hist = self.get_history(count=self.params.ma_period, symbol=symbol, field="close")
        if hist is None or len(hist) < self.params.ma_period:
            return None
        return float(np.mean(hist))

    def on_bar(self, bar):
        ma = self._calc_ma(bar.symbol)
        if ma is None:
            return
        pos = self.get_position(bar.symbol)
        if bar.close > ma and pos <= 0:
            self.buy(symbol=bar.symbol, quantity=100)
        elif bar.close < ma and pos > 0:
            self.close_position(symbol=bar.symbol)


# ---------------------------------------------------------------------------
# 策略 3：单均线趋势 + 止损止盈增强版
# ---------------------------------------------------------------------------
class MA60WithStopStrategy(Strategy):
    """单均线趋势过滤 + 固定比例止损/止盈增强。

    入场：收盘价站上 MA60 → 买入
    出场（任一触发）：
      1. 跌破 MA60 → 清仓（趋势反转离场）
      2. 浮亏超过 stop_loss_pct → 止损离场
      3. 浮盈超过 take_profit_pct → 止盈离场（落袋为安）

    止损止盈基于入场价（entry_price）按收盘价判断，采用 A 股 T+1 语义。
    """

    ma_period = IntParam(60, ge=5, le=250, title="均线周期")
    stop_loss_pct = FloatParam(0.08, ge=0.01, le=0.5, title="止损比例")
    take_profit_pct = FloatParam(0.20, ge=0.02, le=1.0, title="止盈比例")

    # 每笔下单占初始资金的比例（组合回测中用于把资金均分到各标的）。
    # 若为 None，则退化为固定 quantity=100（兼容旧的单标的研究用法）。
    position_pct = FloatParam(0.1, ge=0.01, le=1.0, title="单笔仓位比例")

    def on_start(self):
        self.set_history_depth(self.params.ma_period + 5)
        self._entry_price = {}

    def _calc_ma(self, symbol):
        # 用 get_history + numpy 手动算均线，避免依赖 self.I() 指标声明机制
        # （在 run_grid_search 多进程 spawn 环境下更稳定）。
        hist = self.get_history(count=self.params.ma_period, symbol=symbol, field="close")
        if hist is None or len(hist) < self.params.ma_period:
            return None
        return float(np.mean(hist))

    def _buy_size(self, price):
        """按仓位比例计算买入数量（ETF 单价低，固定 100 手会导致仓位失真）。

        取 min(整手向下取整, 现金允许的最大数量)，A 股按 100 股为 1 手。
        若按仓位预算算出的数量不足 1 手（高单价标的，如指数点位），
        则在现金允许的前提下至少买入 1 手，避免因向下取整导致无法建仓。
        """
        budget = self.cash * self.params.position_pct
        qty = int(budget / price / 100) * 100
        # 高单价标的：预算不足 1 手，但现金足够 1 手 → 退化为买 1 手
        if qty == 0 and budget > 0 and self.cash >= price * 100:
            qty = 100
        return max(qty, 0)

    def on_bar(self, bar):
        ma = self._calc_ma(bar.symbol)
        if ma is None:
            return

        sym = bar.symbol
        pos = self.get_position(sym)
        entry = self._entry_price.get(sym)

        # 空仓 → 判断入场
        if pos <= 0:
            if bar.close > ma:
                qty = self._buy_size(bar.close)
                if qty > 0:
                    self.buy(symbol=sym, quantity=qty)
                    self._entry_price[sym] = bar.close
            return

        # 持仓 → 判断离场（止损 / 止盈 / 趋势反转）
        pnl_pct = (bar.close - entry) / entry if entry else 0.0

        if pnl_pct <= -self.params.stop_loss_pct:
            self.close_position(symbol=sym)
            self._entry_price.pop(sym, None)
        elif pnl_pct >= self.params.take_profit_pct:
            self.close_position(symbol=sym)
            self._entry_price.pop(sym, None)
        elif bar.close < ma:
            self.close_position(symbol=sym)
            self._entry_price.pop(sym, None)


# ---------------------------------------------------------------------------
# 策略 4：单均线趋势 + 追踪止损（Trailing Stop）
# ---------------------------------------------------------------------------
class MA60TrailingStopStrategy(Strategy):
    """单均线趋势过滤 + 追踪止损。

    入场后记录持仓期间最高价，当价格从最高点回撤超过 trail_pct 时离场，
    让利润奔跑、锁定回撤。相比固定止盈更能吃到趋势的完整波段。

    出场（任一触发）：
      1. 跌破 MA60 → 清仓
      2. 价格自持仓最高点回撤 > trail_pct → 追踪止损离场
    """

    ma_period = IntParam(60, ge=5, le=250, title="均线周期")
    trail_pct = FloatParam(0.10, ge=0.02, le=0.5, title="追踪回撤比例")

    def on_start(self):
        self.set_history_depth(self.params.ma_period + 5)
        self._peak = {}   # 持仓期间最高价

    def _calc_ma(self, symbol):
        hist = self.get_history(count=self.params.ma_period, symbol=symbol, field="close")
        if hist is None or len(hist) < self.params.ma_period:
            return None
        return float(np.mean(hist))

    def on_bar(self, bar):
        ma = self._calc_ma(bar.symbol)
        if ma is None:
            return

        sym = bar.symbol
        pos = self.get_position(sym)

        if pos <= 0:
            if bar.close > ma:
                self.buy(symbol=sym, quantity=100)
                self._peak[sym] = bar.close
            return

        # 更新持仓最高价
        if bar.close > self._peak.get(sym, 0):
            self._peak[sym] = bar.close

        peak = self._peak.get(sym, bar.close)
        drawdown_from_peak = (bar.close - peak) / peak if peak else 0.0

        if drawdown_from_peak <= -self.params.trail_pct:
            self.close_position(symbol=sym)
            self._peak.pop(sym, None)
        elif bar.close < ma:
            self.close_position(symbol=sym)
            self._peak.pop(sym, None)


# ---------------------------------------------------------------------------
# 策略 5：单均线趋势 + 固定止损 + 回调止盈（组合版）
# ---------------------------------------------------------------------------
class MA60StopTrailStrategy(Strategy):
    """单均线趋势过滤 + 固定止损 + 回调止盈。

    入场：收盘价站上 MA60 → 买入
    出场（任一触发）：
      1. 浮亏超过 stop_loss_pct → 固定止损离场（快速切断亏损）
      2. 价格自持仓最高点回撤超过 trail_pct → 回调止盈离场（让利润奔跑）
      3. 跌破 MA60 → 趋势反转离场

    相比固定止盈：不设固定盈利目标，用追踪回撤锁定利润，
    能吃到更大的趋势波段；同时用固定止损兜底，避免单笔巨亏。
    """

    ma_period = IntParam(60, ge=5, le=250, title="均线周期")
    stop_loss_pct = FloatParam(0.05, ge=0.01, le=0.5, title="止损比例")
    trail_pct = FloatParam(0.10, ge=0.02, le=0.5, title="回调止盈比例")

    def on_start(self):
        self.set_history_depth(self.params.ma_period + 5)
        self._entry_price = {}
        self._peak = {}

    def _calc_ma(self, symbol):
        hist = self.get_history(count=self.params.ma_period, symbol=symbol, field="close")
        if hist is None or len(hist) < self.params.ma_period:
            return None
        return float(np.mean(hist))

    def on_bar(self, bar):
        ma = self._calc_ma(bar.symbol)
        if ma is None:
            return

        sym = bar.symbol
        pos = self.get_position(sym)
        entry = self._entry_price.get(sym)

        # 空仓 → 判断入场
        if pos <= 0:
            if bar.close > ma:
                self.buy(symbol=sym, quantity=100)
                self._entry_price[sym] = bar.close
                self._peak[sym] = bar.close
            return

        # 更新持仓最高价
        if bar.close > self._peak.get(sym, 0):
            self._peak[sym] = bar.close

        # 1) 固定止损
        pnl_pct = (bar.close - entry) / entry if entry else 0.0
        if pnl_pct <= -self.params.stop_loss_pct:
            self.close_position(symbol=sym)
            self._entry_price.pop(sym, None)
            self._peak.pop(sym, None)
            return

        # 2) 回调止盈（从最高点回撤）
        peak = self._peak.get(sym, bar.close)
        dd_from_peak = (bar.close - peak) / peak if peak else 0.0
        if dd_from_peak <= -self.params.trail_pct:
            self.close_position(symbol=sym)
            self._entry_price.pop(sym, None)
            self._peak.pop(sym, None)
            return

        # 3) 趋势反转
        if bar.close < ma:
            self.close_position(symbol=sym)
            self._entry_price.pop(sym, None)
            self._peak.pop(sym, None)


# ---------------------------------------------------------------------------
# 策略 6：分 3 笔金字塔建仓 + 固定止损止盈
# ---------------------------------------------------------------------------
class MA60Batch3Strategy(Strategy):
    """单均线趋势过滤 + 分 3 笔金字塔建仓 + 固定止损止盈。

    入场：收盘价站上 MA60 → 买入第 1 笔（总资金 1/3）
    补仓：持仓后每下跌 add_step 幅度 → 补一笔（越跌越买，摊低成本），最多 3 笔
    出场（任一触发，按整体成本计算）：
      1. 整体浮亏超过 stop_loss_pct → 全仓止损
      2. 整体浮盈超过 take_profit_pct → 全仓止盈
      3. 跌破 MA60 → 趋势反转全仓离场

    每笔买入金额 = 初始现金 / 3（等额分批）。
    """

    ma_period = IntParam(60, ge=5, le=250, title="均线周期")
    add_step = FloatParam(0.03, ge=0.01, le=0.3, title="补仓间隔（下跌幅度）")
    stop_loss_pct = FloatParam(0.05, ge=0.01, le=0.5, title="止损比例")
    take_profit_pct = FloatParam(0.30, ge=0.05, le=2.0, title="止盈比例")

    def on_start(self):
        self.set_history_depth(self.params.ma_period + 5)
        self._lots = {}          # symbol -> 已买入笔数
        self._cost = {}          # symbol -> 整体成本价（加权）
        self._last_add_price = {}  # symbol -> 上次补仓时的价格（用于判断下一档）

    def _calc_ma(self, symbol):
        hist = self.get_history(count=self.params.ma_period, symbol=symbol, field="close")
        if hist is None or len(hist) < self.params.ma_period:
            return None
        return float(np.mean(hist))

    def on_bar(self, bar):
        ma = self._calc_ma(bar.symbol)
        if ma is None:
            return

        sym = bar.symbol
        pos = self.get_position(sym)
        lots = self._lots.get(sym, 0)
        cost = self._cost.get(sym)
        last_add = self._last_add_price.get(sym)

        # ---- 空仓 → 首次入场（第 1 笔）----
        if pos <= 0:
            if bar.close > ma:
                self.buy(symbol=sym, quantity=100)
                self._lots[sym] = 1
                self._cost[sym] = bar.close
                self._last_add_price[sym] = bar.close
            return

        # ---- 持仓 → 补仓 / 出场判断 ----
        # 越跌越买：距上次补仓价下跌 add_step 且未满 3 笔 → 补仓
        if lots < 3 and last_add is not None:
            if bar.close <= last_add * (1 - self.params.add_step):
                self.buy(symbol=sym, quantity=100)
                new_lots = lots + 1
                self._lots[sym] = new_lots
                # 等额买入，整体成本 = (旧成本*旧笔数 + 新价) / 新笔数
                self._cost[sym] = (cost * lots + bar.close) / new_lots
                self._last_add_price[sym] = bar.close
                return

        # 整体浮盈/浮亏（按加权成本）
        cost = self._cost.get(sym)
        if cost is None or cost == 0:
            return
        pnl_pct = (bar.close - cost) / cost

        if pnl_pct <= -self.params.stop_loss_pct:
            self.close_position(symbol=sym)
            self._reset(sym)
        elif pnl_pct >= self.params.take_profit_pct:
            self.close_position(symbol=sym)
            self._reset(sym)
        elif bar.close < ma:
            self.close_position(symbol=sym)
            self._reset(sym)

    def _reset(self, sym):
        self._lots.pop(sym, None)
        self._cost.pop(sym, None)
        self._last_add_price.pop(sym, None)


# ---------------------------------------------------------------------------
# 绩效工具
# ---------------------------------------------------------------------------
def _g(m, name, default=None):
    try:
        return getattr(m, name)
    except AttributeError:
        return default


def summarize(name, result):
    """打印策略绩效摘要。"""
    m = result.metrics
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    total_ret = _g(m, "total_return_pct")
    ann = _g(m, "annualized_return")
    mdd = _g(m, "max_drawdown_pct")
    sharpe = _g(m, "sharpe_ratio")
    win = _g(m, "win_rate")
    trades = _g(m, "closed_trade_count")
    profit_factor = _g(m, "profit_factor")
    exposure = _g(m, "exposure_time_pct")

    def pct(v):
        return f"{v:.2f}%" if v is not None else "N/A"
    def pct100(v):
        return f"{v*100:.2f}%" if v is not None else "N/A"

    print(f"  累计收益率    : {pct(total_ret)}")
    print(f"  年化收益率    : {pct100(ann)}")
    print(f"  最大回撤      : {pct(mdd)}")
    print(f"  夏普比率      : {sharpe:.3f}" if sharpe is not None else "  夏普比率: N/A")
    print(f"  胜率          : {win:.1f}%" if win is not None else "  胜率: N/A")
    print(f"  交易次数      : {trades:.0f}" if trades is not None else "  交易次数: N/A")
    print(f"  盈亏比(Profit Factor): {profit_factor:.2f}" if profit_factor is not None else "")
    print(f"  持仓时间占比  : {exposure:.1f}%" if exposure is not None else "")
    return total_ret, mdd


def buy_hold_benchmark(df):
    """买入持有基准：累计收益 + 最大回撤。"""
    closes = df["close"].values
    first, last = closes[0], closes[-1]
    total = (last / first - 1) * 100
    peak = np.maximum.accumulate(closes)
    dd = (closes - peak) / peak
    return total, dd.min() * 100
