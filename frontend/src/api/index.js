import axios from 'axios'

const http = axios.create({
  baseURL: '/api',
  timeout: 120000, // 驾驶舱动态渲染较慢，放宽超时
})

http.interceptors.response.use(
  (resp) => resp.data,
  (err) => {
    const detail = err?.response?.data?.detail || err.message || '请求失败'
    return Promise.reject(new Error(detail))
  }
)

// ---- 持仓 ----
export const getQuotes = () => http.get('/quotes')
export const addPosition = (data) => http.post('/position', data)
export const deletePosition = (code) => http.delete(`/position/${encodeURIComponent(code)}`)
export const clearPositions = () => http.delete('/positions')

// ---- 策略台账 ----
export const getStrategyOverview = () => http.get('/strategy/overview')
export const getStrategyHistory = (strategy, limit = 500) =>
  http.get(`/strategy/${strategy}/history`, { params: { limit } })
export const getStrategySeries = (strategy, metric, limit = 500) =>
  http.get(`/strategy/${strategy}/series`, { params: { metric, limit } })

// ---- 交易日志 ----
export const getTrades = (params) => http.get('/trade', { params })
export const addTrade = (data) => http.post('/trade', data)
export const updateTrade = (id, data) => http.put(`/trade/${id}`, data)
export const deleteTrade = (id) => http.delete(`/trade/${id}`)

// ---- 驾驶舱 ----
export const getDashboards = () => http.get('/dashboards')
export const getDashboardHtml = (key) =>
  http.get(`/dashboards/${key}`, { responseType: 'text' })

export default http
