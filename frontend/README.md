# frontend —— 个人投资管理后台（前端，前后端分离）

基于 **Vue 3 + Vite + Ant Design Vue** 的前端项目，通过 HTTP 调用后端 `portfolio/server.py` 的纯 JSON API。

## 技术栈

- Vue 3（`<script setup>` 组合式 API）
- Vite 6（开发服务器 + 构建）
- Ant Design Vue 4（UI 组件库）
- Vue Router 4（路由）
- Axios（HTTP 请求）
- ECharts 5（策略趋势图）

## 目录结构

```
frontend/
├── index.html              # 入口 HTML
├── package.json
├── vite.config.js          # 开发代理：/api → http://127.0.0.1:8765
└── src/
    ├── main.js             # 应用入口，注册 Antd + Router
    ├── App.vue             # 主布局（侧边栏 + 路由视图）
    ├── style.css           # 全局样式（红涨绿跌变量）
    ├── router/index.js     # 4 个路由
    ├── api/index.js        # 后端 API 封装
    └── views/
        ├── Portfolio.vue   # 持仓（盈亏 + 实时行情）
        ├── Strategy.vue    # 策略台账（历史趋势图）
        ├── Trade.vue       # 交易日志（原因 + 复盘）
        └── Dashboards.vue  # 驾驶舱（iframe 嵌入后端动态渲染）
```

## 开发运行（前后端两个进程）

```bash
# 1. 启动后端（纯 API，端口 8765）
cd ..
.venv/Scripts/python.exe -m portfolio.server 8765

# 2. 启动前端（Vite dev server，端口 5173）
cd frontend
npm install        # 首次运行先装依赖
npm run dev
```

浏览器打开 **http://localhost:5173** 即可。

> 开发时 Vite 已配置代理，`/api/*` 请求会自动转发到 `http://127.0.0.1:8765`，无需处理跨域。

## 生产构建

```bash
npm run build       # 产物输出到 dist/
npm run preview     # 本地预览构建产物
```

## 说明

- **红涨绿跌**：沿用 A 股习惯，涨红（`#f5222d`）跌绿（`#52c41a`），在 `src/style.css` 里用 `--up` / `--down` 变量定义。
- **驾驶舱**：`Dashboards.vue` 用 iframe 直接嵌入后端 `/api/dashboards/{key}` 返回的 HTML（后端实时拉数据生成）。iframe 不走 axios 代理，故源码里写死了后端地址 `http://127.0.0.1:8765`。
- **ECharts 已离线化**：驾驶舱 HTML 引用后端的 `/static/echarts.min.js`（本地文件，非 CDN），内网/离线环境图表也能正常显示。
