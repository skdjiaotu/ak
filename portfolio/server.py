"""portfolio 后端服务 —— 纯 API（前后端分离）。

只提供 JSON 接口，不再 serve 任何 HTML 页面。前端为独立项目（frontend/，
Vue3 + Ant Design Vue），通过 HTTP 调用本服务。

接口一览：
    GET    /api/quotes          → 持仓 + 实时行情 + 盈亏汇总
    POST   /api/position        → 新增/更新持仓（同代码覆盖）
    DELETE /api/position/{code} → 删除指定持仓
    DELETE /api/positions       → 清空全部持仓
    GET    /api/strategy/overview      → 台账概览 + 最新信号
    GET    /api/strategy/{s}/history   → 某策略历史快照
    GET    /api/strategy/{s}/series    → 某策略某指标时间序列
    GET    /api/trade           → 交易日志列表 + 统计
    POST   /api/trade           → 新增交易
    PUT    /api/trade/{id}      → 更新交易
    DELETE /api/trade/{id}      → 删除交易
    GET    /api/dashboards      → 驾驶舱列表
    GET    /api/dashboards/{key}→ 动态渲染驾驶舱 HTML
    GET    /docs                → Swagger 文档

启动：
    .venv/Scripts/python.exe -m portfolio.server [port]

    # 或直接 uvicorn
    .venv/Scripts/python.exe -m uvicorn portfolio.server:app --host 127.0.0.1 --port 8765
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from portfolio import store
from portfolio.quotes import enrich_positions

# 项目根目录（用于挂载共享静态资源，如 ECharts）
ROOT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT_DIR / "static"

app = FastAPI(
    title="个人投资管理后台 API",
    description="持仓管理 + 策略台账 + 交易日志 + 驾驶舱（纯 JSON 接口，前后端分离）",
    version="2.0.0",
)

# 挂载共享静态资源（ECharts 等），供驾驶舱 HTML 引用
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# 允许前端（Vite dev server 等）跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 本地开发放开；如需收紧可改为具体 origin
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PositionIn(BaseModel):
    """新增/更新持仓的请求体。"""

    code: str = Field(..., description="股票代码，如 600519 / sz000858")
    name: str = ""
    cost: float = Field(..., gt=0, description="成本价（元/股）")
    shares: float = Field(..., gt=0, description="持仓数量（股）")
    bought_at: str = ""
    note: str = ""


@app.get("/api/quotes")
def get_quotes():
    """返回持仓列表（含实时行情与盈亏）及汇总。"""
    try:
        return enrich_positions(store.load())
    except Exception as e:  # noqa
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/position")
def add_position(item: PositionIn):
    """新增或更新一笔持仓（同代码覆盖）。"""
    try:
        rec = store.add(item.model_dump())
        return {"ok": True, "position": rec}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/position/{code}")
def delete_position(code: str):
    """删除指定代码的持仓。"""
    ok = store.remove(code)
    return {"ok": ok, "code": code}


@app.delete("/api/positions")
def clear_positions():
    """清空全部持仓。"""
    n = store.clear()
    return {"ok": True, "cleared": n}


# ---------------------------------------------------------------------------
# 策略台账（strategy_log）接口
# ---------------------------------------------------------------------------

@app.get("/api/strategy/overview")
def strategy_overview():
    """台账概览 + 策略列表 + 最新信号。"""
    import strategy_log as sl
    strategies = sl.list_strategies()
    latest_map = {}
    for s in strategies:
        rec = sl.latest(s)
        if rec:
            latest_map[s] = {
                "run_date": rec["run_date"],
                "payload": rec["payload"],
            }
    return {
        "stats": sl.stats(),
        "strategies": strategies,
        "latest": latest_map,
    }


@app.get("/api/strategy/{strategy}/history")
def strategy_history(strategy: str, limit: int = 500):
    """某策略的历史快照。"""
    import strategy_log as sl
    return {"strategy": strategy, "history": sl.history(strategy, limit=limit)}


@app.get("/api/strategy/{strategy}/series")
def strategy_series(strategy: str, metric: str, limit: int = 500):
    """某策略某指标的时间序列。"""
    import strategy_log as sl
    return {
        "strategy": strategy,
        "metric": metric,
        "series": sl.series(strategy, metric, limit=limit),
    }


# ---------------------------------------------------------------------------
# 交易日志（trade_log）接口
# ---------------------------------------------------------------------------

class TradeIn(BaseModel):
    """交易日志请求体。"""

    code: str = Field(..., description="股票代码")
    name: str = ""
    direction: str = Field("buy", description="buy 买入 / sell 卖出")
    trade_date: str = ""
    price: float = Field(..., gt=0)
    shares: float = Field(..., gt=0)
    reason: str = ""
    review: str = ""
    tags: list[str] = []
    note: str = ""


@app.get("/api/trade")
def trade_list(limit: int = 500, offset: int = 0):
    """交易日志列表 + 统计。"""
    import trade_log as tl
    return {"trades": tl.list_all(limit=limit, offset=offset), "stats": tl.stats()}


@app.post("/api/trade")
def trade_add(item: TradeIn):
    """新增一笔交易。"""
    import trade_log as tl
    try:
        rec = tl.add(item.model_dump())
        return {"ok": True, "trade": rec}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/trade/{trade_id}")
def trade_update(trade_id: int, item: TradeIn):
    """更新一笔交易。"""
    import trade_log as tl
    try:
        rec = tl.update(trade_id, item.model_dump())
        if rec is None:
            raise HTTPException(status_code=404, detail="交易不存在")
        return {"ok": True, "trade": rec}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/trade/{trade_id}")
def trade_delete(trade_id: int):
    """删除一笔交易。"""
    import trade_log as tl
    ok = tl.remove(trade_id)
    return {"ok": ok}


# ---------------------------------------------------------------------------
# 驾驶舱（gem_position / star_position / sentiment 的实时看板）
# ---------------------------------------------------------------------------

DASHBOARDS = {
    "gem": {"title": "创业板位置驾驶舱", "module": "gem_position.dashboard"},
    "star": {"title": "科创板位置驾驶舱", "module": "star_position.dashboard"},
    "sentiment": {"title": "市场情绪驾驶舱", "module": "sentiment.dashboard"},
}


@app.get("/api/dashboards")
def dashboards_list():
    """驾驶舱列表。"""
    return {
        "dashboards": [
            {"key": k, "title": v["title"]} for k, v in DASHBOARDS.items()
        ]
    }


@app.get("/api/dashboards/{key}")
def dashboard_render(key: str):
    """动态渲染某个驾驶舱（实时拉数据，返回完整 HTML）。"""
    if key not in DASHBOARDS:
        raise HTTPException(status_code=404, detail="驾驶舱不存在")
    import importlib
    try:
        mod = importlib.import_module(DASHBOARDS[key]["module"])
        html = mod.build_dashboard()
        from fastapi.responses import HTMLResponse
        return HTMLResponse(html)
    except Exception as e:  # noqa
        raise HTTPException(status_code=500, detail=f"驾驶舱生成失败: {e}")


def run(port: int = 8765):
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    import sys

    p = 8765
    if len(sys.argv) > 1:
        p = int(sys.argv[1])
    run(p)
