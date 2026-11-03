# portfolio —— 个人投资管理后端（纯 API）

持仓管理 + 策略台账 + 交易日志 + 驾驶舱的**后端服务**，只提供 JSON API，不渲染页面。

前端是独立的 Vue3 项目（`../frontend/`），通过 HTTP 调用本服务的 `/api/*` 接口。

## 快速开始

后端基于 **FastAPI + Uvicorn**（前后端分离）。

```bash
# 单独启动后端（默认端口 8765）
.venv/Scripts/python.exe -m portfolio.server

# 或直接 uvicorn
.venv/Scripts/python.exe -m uvicorn portfolio.server:app --host 127.0.0.1 --port 8765 --reload
```

> 完整的前后端一键启动请用项目根目录的 `start.py`（`python start.py`），会同时拉起后端(8765)和前端(5173)。

- 交互式 API 文档（Swagger）：http://127.0.0.1:8765/docs

## 功能

- **持仓**：增删改查，数据存本地 `portfolio/data.json`；新浪实时行情 + 盈亏汇总。
- **策略台账**：读取 `strategy_log` 的 SQLite 数据，提供概览/历史/指标序列接口。
- **交易日志**：`trade_log` 的 CRUD 接口。
- **驾驶舱**：动态渲染创业板/科创板/市场情绪三个驾驶舱 HTML。

## 代码结构

| 文件 | 职责 |
|------|------|
| `store.py` | 持仓数据模型 + JSON 持久化（增删改查） |
| `quotes.py` | 新浪实时行情批量拉取 + 盈亏计算 |
| `server.py` | FastAPI 应用（纯 API + CORS）+ Uvicorn 启动入口 |

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/quotes` | 持仓 + 行情 + 盈亏汇总 |
| POST | `/api/position` | 新增/更新持仓（同代码覆盖） |
| DELETE | `/api/position/{code}` | 删除指定代码 |
| DELETE | `/api/positions` | 清空全部 |
| GET | `/api/strategy/overview` | 台账概览 + 最新信号 |
| GET | `/api/strategy/{s}/history` | 某策略历史快照 |
| GET | `/api/strategy/{s}/series` | 某策略某指标时间序列 |
| GET | `/api/trade` | 交易日志列表 + 统计 |
| POST | `/api/trade` | 新增交易 |
| PUT | `/api/trade/{id}` | 更新交易 |
| DELETE | `/api/trade/{id}` | 删除交易 |
| GET | `/api/dashboards` | 驾驶舱列表 |
| GET | `/api/dashboards/{key}` | 动态渲染驾驶舱 HTML |

请求体通过 Pydantic 自动校验（`code` 必填，`cost`/`shares` 必须 > 0），非法输入返回结构化 422/400 错误。

## 股票代码规则

支持直接输入数字，自动识别市场：

- `6xxxxx` / `5xxxxx` / `9xxxxx` → 上海（sh）
- `0xxxxx` / `3xxxxx` / `1xxxxx` / `2xxxxx` → 深圳（sz）
- `4xxxxx` / `8xxxxx` → 北交所（bj）

也可以直接输入 `sh600519` / `sz000858` 这种带前缀的完整代码。

## 说明

- 行情数据约 15 秒延迟，仅供个人参考，不构成投资建议。
- 数据仅保存在本机，无任何上传。
