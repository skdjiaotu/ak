# -*- coding: utf-8 -*-
"""
中大盘股池历史行情拉取（腾讯前复权，带缓存）

股票池：上证50 + 沪深300 + 中证500 + 科创50 + 创业板指 合并去重，
每指数按成交额(amount)取靠前的代表，控制总数量，避免拉取超时。
"""
import os
import pickle
import time
import numpy as np
import pandas as pd
import akshare as ak

CACHE_DIR = "../stock/cache"
POOL_CACHE = os.path.join(CACHE_DIR, "midcap_pool.pkl")
PRICE_CACHE = os.path.join(CACHE_DIR, "midcap_price.csv")


def build_representative_pool(per_index=60):
    """每指数取成交额靠前的 per_index 只，合并去重。"""
    with open(POOL_CACHE, "rb") as f:
        pool = pickle.load(f)  # code -> {name, idx, amount}

    # 按指数分组，每指数取 amount 最大的前 per_index 只
    selected = set()
    # 指数顺序（先大盘再小盘）
    order = ["上证50", "沪深300", "科创50", "创业板指", "中证500"]
    idx_codes = {nm: [] for nm in order}
    for c, v in pool.items():
        for nm in v["idx"]:
            if nm in idx_codes:
                idx_codes[nm].append(c)

    for nm in order:
        codes = idx_codes[nm]
        # 按成交额降序
        codes_sorted = sorted(codes, key=lambda c: (pool[c].get("amount") or 0), reverse=True)
        for c in codes_sorted[:per_index]:
            selected.add(c)

    return sorted(selected)


def to_tx_symbol(code):
    if code.startswith(("6", "5", "9")):
        return "sh" + code
    return "sz" + code


def build_price_panel(codes, cache_path=PRICE_CACHE):
    if os.path.exists(cache_path):
        return pd.read_csv(cache_path, index_col=0, parse_dates=True)

    closes = {}
    total = len(codes)
    t0 = time.time()
    for i, code in enumerate(codes):
        sym = to_tx_symbol(code)
        try:
            df = ak.stock_zh_a_hist_tx(symbol=sym, start_date="20180101",
                                       end_date="20261030")
            if len(df):
                df = df.sort_values("date")
                closes[code] = df.set_index("date")["close"]
        except Exception as e:
            print(f"  [跳过] {code}: {str(e)[:50]}", flush=True)
        if (i + 1) % 30 == 0:
            el = time.time() - t0
            print(f"  已拉 {i+1}/{total} 只，用时 {el:.0f}s，预计还需 {(total-i-1)*4:.0f}s",
                  flush=True)
        time.sleep(0.2)

    panel = pd.DataFrame(closes).sort_index()
    os.makedirs(CACHE_DIR, exist_ok=True)
    panel.to_csv(cache_path)
    print(f"  完成！面板 {panel.shape[0]} 日 × {panel.shape[1]} 只，"
          f"总用时 {(time.time()-t0)/60:.1f} 分钟", flush=True)
    return panel


if __name__ == "__main__":
    codes = build_representative_pool(per_index=60)
    print(f"代表股票池：{len(codes)} 只", flush=True)
    panel = build_price_panel(codes)
