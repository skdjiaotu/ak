<script setup>
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import {
  WalletOutlined,
  DashboardOutlined,
  LineChartOutlined,
  FileTextOutlined,
} from '@ant-design/icons-vue'

const route = useRoute()

const menus = [
  { path: '/', title: '持仓', icon: WalletOutlined },
  { path: '/dashboards', title: '驾驶舱', icon: DashboardOutlined },
  { path: '/strategy', title: '策略台账', icon: LineChartOutlined },
  { path: '/trade', title: '交易日志', icon: FileTextOutlined },
]

const selectedKey = computed(() => {
  const found = menus.find((m) => m.path === route.path)
  return found ? [found.path] : ['/']
})
</script>

<template>
  <a-layout style="min-height: 100vh">
    <a-layout-sider
      v-model:collapsed="collapsed"
      collapsible
      theme="dark"
      :trigger="null"
      width="220"
    >
      <div class="logo">
        <span class="logo-dot"></span>
        <span v-if="!collapsed">投资管理后台</span>
      </div>
      <a-menu v-model:selectedKeys="selectedKey" theme="dark" mode="inline">
        <a-menu-item v-for="m in menus" :key="m.path">
          <router-link :to="m.path">
            <component :is="m.icon" />
            <span>{{ m.title }}</span>
          </router-link>
        </a-menu-item>
      </a-menu>
    </a-layout-sider>

    <a-layout>
      <a-layout-header class="header">
        <a-button type="text" @click="collapsed = !collapsed" class="collapse-btn">
          <template #icon>
            <span class="hamburger"></span>
          </template>
        </a-button>
        <span class="header-title">{{ route.meta.title }}</span>
      </a-layout-header>
      <a-layout-content class="content">
        <router-view />
      </a-layout-content>
    </a-layout>
  </a-layout>
</template>

<script>
export default {
  data() {
    return { collapsed: false }
  },
}
</script>

<style>
.logo {
  height: 56px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 20px;
  color: #fff;
  font-weight: 600;
  font-size: 16px;
  overflow: hidden;
  white-space: nowrap;
}
.logo-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #1677ff;
  box-shadow: 0 0 8px #1677ff;
  flex-shrink: 0;
}
.header {
  background: #fff;
  padding: 0 20px;
  display: flex;
  align-items: center;
  gap: 12px;
  height: 56px;
  line-height: 56px;
  border-bottom: 1px solid #f0f0f0;
}
.collapse-btn {
  display: flex;
  align-items: center;
}
.hamburger {
  width: 18px;
  height: 2px;
  background: #333;
  display: inline-block;
  position: relative;
}
.hamburger::before,
.hamburger::after {
  content: '';
  position: absolute;
  left: 0;
  width: 18px;
  height: 2px;
  background: #333;
}
.hamburger::before {
  top: -5px;
}
.hamburger::after {
  top: 5px;
}
.header-title {
  font-size: 16px;
  font-weight: 600;
  color: #333;
}
.content {
  padding: 20px;
  background: #f5f6f8;
}
</style>
