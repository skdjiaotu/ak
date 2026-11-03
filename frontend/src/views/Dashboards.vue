<script setup>
import { ref, onMounted, computed } from 'vue'
import { message } from 'ant-design-vue'
import { ReloadOutlined, ExportOutlined } from '@ant-design/icons-vue'
import { getDashboards } from '../api'

const dashboards = ref([])
const activeKey = ref('')
const loading = ref(false)
const frameLoading = ref(false)
const frameError = ref(false)
const frameKey = ref(0) // 用于强制刷新 iframe

// 直接指向后端（iframe src 不走 axios 代理，需写完整地址）
const API_BASE = 'http://127.0.0.1:8765'

const activeSrc = computed(() => {
  if (!activeKey.value) return ''
  return `${API_BASE}/api/dashboards/${activeKey.value}`
})

const titleMap = {
  gem: '创业板位置驾驶舱',
  star: '科创板位置驾驶舱',
  sentiment: '市场情绪驾驶舱',
}

async function load() {
  loading.value = true
  try {
    const d = await getDashboards()
    dashboards.value = d.dashboards
    if (d.dashboards.length && !activeKey.value) {
      activeKey.value = d.dashboards[0].key
    }
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = false
  }
}

function switchDashboard(key) {
  activeKey.value = key
  frameLoading.value = true
  frameError.value = false
  frameKey.value++ // 重新挂载 iframe，触发重新加载
}

function onFrameLoad() {
  frameLoading.value = false
}

function onFrameError() {
  frameLoading.value = false
  frameError.value = true
}

function refresh() {
  if (!activeKey.value) return
  frameLoading.value = true
  frameError.value = false
  frameKey.value++
}

function openInNewTab() {
  if (activeSrc.value) window.open(activeSrc.value, '_blank')
}

onMounted(load)
</script>

<template>
  <div>
    <a-card :loading="loading">
      <div class="toolbar">
        <a-space wrap>
          <span>选择驾驶舱：</span>
          <a-radio-group :value="activeKey" button-style="solid" @change="(e) => switchDashboard(e.target.value)">
            <a-radio-button v-for="d in dashboards" :key="d.key" :value="d.key">
              {{ d.title }}
            </a-radio-button>
          </a-radio-group>
        </a-space>
        <a-space>
          <a-button @click="refresh" :disabled="!activeKey">
            <template #icon><ReloadOutlined /></template>
            刷新
          </a-button>
          <a-button @click="openInNewTab" :disabled="!activeKey">
            <template #icon><ExportOutlined /></template>
            新窗口打开
          </a-button>
        </a-space>
      </div>

      <div class="frame-wrap">
        <div v-if="frameLoading" class="frame-mask">
          <a-spin size="large" tip="正在加载最新数据...">
            <div style="min-height: 120px"></div>
          </a-spin>
        </div>
        <iframe
          v-if="activeSrc"
          :key="frameKey"
          :src="activeSrc"
          :title="titleMap[activeKey] || '驾驶舱'"
          class="frame"
          @load="onFrameLoad"
          @error="onFrameError"
        ></iframe>
        <a-empty v-else description="加载中..." />
      </div>

      <div v-if="frameError" class="err-tip">
        <a-alert
          type="error"
          show-icon
          message="驾驶舱加载失败"
          description="可能是后端未启动或数据拉取超时。请确认后端服务(8765)正在运行，然后点击「刷新」重试。"
        />
      </div>
    </a-card>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 16px;
}
.frame-wrap {
  position: relative;
  height: calc(100vh - 240px);
  min-height: 560px;
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
}
.frame {
  width: 100%;
  height: 100%;
  border: none;
  display: block;
}
.frame-mask {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #fff;
  z-index: 10;
}
.err-tip {
  margin-top: 12px;
}
</style>
