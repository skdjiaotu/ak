"""市场情绪多因子信号合成引擎。

把 7 个情绪/资金面因子合成一个「情绪热度评分」，再映射为择时仓位。

核心思路：
  1. 每个因子先做滚动标准化（z-score，滚动窗口 24 个月），消除量纲差异。
  2. 对「反向因子」（波动率指数 qvix）取负号，使所有因子方向统一为
     「越大 = 情绪越热/越危险」。
  3. 等权合成 → 得到综合情绪热度 z-score。
  4. 情绪热度映射为仓位：过热 → 减仓/空仓，冰点 → 加仓/满仓。
     （逆向思维：众人贪婪我恐惧，众人恐惧我贪婪）

因子方向约定（sign，正号=值越大越热/越危险）：
  turnover  换手率        +  高换手 = 情绪亢奋
  amount    成交额        +  放量 = 情绪亢奋
  margin    融资余额      +  加杠杆 = 亢奋
  new_account 新增开户    +  散户跑步入场 = 亢奋
  fund_count 基金发行只数  +  爆款频出 = 亢奋
  fund_share 基金发行份额  +  爆款频出 = 亢奋
  erp       股债性价比    -  ERP 高 = 股票便宜（逆向：越高越该买）
  qvix      波动率指数    -  恐慌指数高 = 该买（逆向）

注意：本模块对数据缺失「自动降级」——某因子某月缺失时，从等权分母中剔除，
不因单因子缺数据而丢弃整月。
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# 因子方向：+1 = 值越大越热/越危险（贡献正向情绪），-1 = 值越大越该买（逆向）
FACTOR_SIGN = {
    "turnover": +1.0,
    "amount": +1.0,
    "margin": +1.0,
    "new_account": +1.0,
    "fund_count": +1.0,
    "fund_share": +1.0,
    "erp": -1.0,
    "qvix": -1.0,
}

# 因子中文名（报告展示用）
FACTOR_CN = {
    "turnover": "换手率",
    "amount": "成交额",
    "margin": "融资余额",
    "new_account": "新增开户数",
    "fund_count": "基金发行只数",
    "fund_share": "基金发行份额",
    "erp": "股债性价比",
    "qvix": "波动率指数",
}


def rolling_zscore(s: pd.Series, window: int = 24, min_periods: int = 12) -> pd.Series:
    """滚动 z-score 标准化：z = (x - rolling_mean) / rolling_std。"""
    mean = s.rolling(window, min_periods=min_periods).mean()
    std = s.rolling(window, min_periods=min_periods).std()
    z = (s - mean) / std
    z[std == 0] = 0.0
    return z


def build_factor_scores(panel: pd.DataFrame, window: int = 24) -> pd.DataFrame:
    """逐因子标准化（带方向符号），返回与 panel 同形状的 score 矩阵。

    score = sign * zscore(因子)，score 越大 = 情绪越热/越危险。
    """
    scores = pd.DataFrame(index=panel.index)
    for col in FACTOR_SIGN:
        if col not in panel.columns:
            continue
        z = rolling_zscore(panel[col], window=window)
        scores[col] = FACTOR_SIGN[col] * z
    return scores


def composite_heat(scores: pd.DataFrame) -> pd.Series:
    """等权合成综合情绪热度（逐行忽略 NaN，动态分母）。

    返回 heat：越大 = 情绪越亢奋/越危险。
    """
    return scores.mean(axis=1)


def heat_to_position(heat: pd.Series,
                     overheat: float = 1.0,
                     ice: float = -1.0) -> pd.Series:
    """情绪热度 → 仓位映射（三段式，逆向思维）。

      heat >= overheat  → 空仓（0.0），情绪过热该撤
      heat <= ice       → 满仓（1.0），情绪冰点该买
      中间              → 线性插值（0~1 阶梯仓位）

    默认阈值 overheat=1.0 / ice=-1.0（即滚动 1 个标准差为过热/冰点分界）。
    """
    pos = pd.Series(np.nan, index=heat.index)
    pos[heat >= overheat] = 0.0
    pos[heat <= ice] = 1.0
    mid = (heat > ice) & (heat < overheat)
    pos[mid] = (overheat - heat[mid]) / (overheat - ice)
    return pos


def current_status(panel: pd.DataFrame, scores: pd.DataFrame, heat: pd.Series,
                   window: int = 24) -> Dict:
    """生成「当前」情绪快照，供报告展示每个因子当前分位与方向。"""
    out: Dict[str, dict] = {}
    for col in FACTOR_SIGN:
        if col not in panel.columns:
            continue
        raw = panel[col]
        cur = raw.dropna()
        if len(cur) == 0:
            continue
        last_val = cur.iloc[-1]
        # 近 3 年分位
        recent = cur.iloc[-min(36, len(cur)):]
        pct = (recent <= last_val).mean() * 100
        out[col] = {
            "cn": FACTOR_CN[col],
            "value": last_val,
            "pct": pct,                       # 近3年分位（0~100）
            "score": scores[col].iloc[-1] if col in scores.columns else None,
            "sign": FACTOR_SIGN[col],
        }
    return out


def factor_effectiveness(scores: pd.DataFrame, fwd_rets: pd.Series,
                         lookback: int = 1) -> pd.DataFrame:
    """单因子有效性：因子 score 与未来 lookback 月指数收益的相关性（IC）。

    正向因子（情绪热）理论上与未来收益负相关（过热→下跌），
    反向因子（erp/qvix）理论上正相关。这里统一看 |IC| 与符号是否符合预期。
    """
    rows = []
    for col in scores.columns:
        s = scores[col]
        aligned = pd.concat([s.rename("s"), fwd_rets.rename("r")], axis=1).dropna()
        if len(aligned) < 24:
            continue
        ic = aligned["s"].corr(aligned["r"])
        expected = -FACTOR_SIGN[col]  # 情绪热(score>0)→未来收益应为负
        rows.append({
            "因子": FACTOR_CN.get(col, col),
            "IC": ic,
            "符合预期": (ic * expected > 0),
        })
    return pd.DataFrame(rows)
