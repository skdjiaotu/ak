import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'portfolio', component: () => import('../views/Portfolio.vue'), meta: { title: '持仓' } },
  { path: '/strategy', name: 'strategy', component: () => import('../views/Strategy.vue'), meta: { title: '策略台账' } },
  { path: '/trade', name: 'trade', component: () => import('../views/Trade.vue'), meta: { title: '交易日志' } },
  { path: '/dashboards', name: 'dashboards', component: () => import('../views/Dashboards.vue'), meta: { title: '驾驶舱' } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
