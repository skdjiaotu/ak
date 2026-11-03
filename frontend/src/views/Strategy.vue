<script setup>
import { ref, onMounted, watch } from 'vue'
import { message } from 'ant-design-vue'
import * as echarts from 'echarts'
import { getStrategyOverview, getStrategySeries } from '../api'

const stats = ref(null)
const strategies = ref([])
const latest = ref({})
const loading = ref(false)

const activeStrategy = ref('')
const metric = ref('')
const chartEl = ref(null)
let chart = null

// 策略核心指标（用于趋势图默认选中）
const metricMap = {
  gem_position: { label: '位置温度', key: 'position_temp' },
  star_position: { label: '位置温度', key: 'position_temp' },
  sentiment: { label: '情绪热度', key: 'heat' },
  daily_report: { label: '整体信号', key: 'score' },
}

const strategyNameMap = {
  gem_position: '创业板位置',
  star_position: '科创板位置',
  sentiment: '市场情绪',
  daily_report: '市场体检',
}

async function load() {
  loading.value = true
  try {
    const d = await getStrategyOverview()
    stats.value = d.stats
    strategies.value = d.strategies
    latest.value = d.latest
    if (d.strategies.length && !activeStrategy.value) {
      activeStrategy.value = d.strategies[0]
    }
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = false
  }
}

async function drawChart() {
  if (!activeStrategy.value) return
  const m = metricMap[activeStrategy.value] || { key: metric.value || 'position_temp', label: '' }
  metric.value = m.key
  try {
    const d = await getStrategySeries(activeStrategy.value, m.key)
    const series = d.series || []
    if (!chart) chart = echarts.init(chartEl.value)
    chart.setOption({
      title: { text: `${strategyNameMap[activeStrategy.value] || activeStrategy.value} · ${m.label}趋势` },
      tooltip: { trigger: 'axis' },
      grid: { left: 50, right: 20, top: 50, bottom: 40 },
      xAxis: {
        type: 'category',
        data: series.map((p) => p.date),
      },
      yAxis: { type: 'value', scale: true },
      series: [
        {
          type: 'line',
          data: series.map((p) => p.value),
          smooth: true,
          areaStyle: { opacity: 0.15 },
          lineStyle: { color: '#1677ff' },
          itemStyle: { color: '#1677ff' },
        },
      ],
    })
  } catch (e) {
    message.error(e.message)
  }
}

watch(activeStrategy, () => drawChart())
onMounted(async () => {
  await load()
  await drawChart()
})
</script>

<template>
  <div>
    <a-row :gutter="16" style="margin-bottom: 16px">
      <a-col :span="8">
        <a-card>
          <a-statistic title="策略数" :value="stats?.strategies ?? 0" />
        </a-card>
      </a-col>
      <a-col :span="8">
        <a-card>
          <a-statistic title="记录天数" :value="stats?.days ?? 0" />
        </a-card>
      </a-col>
      <a-col :span="8">
        <a-card>
          <a-statistic title="记录总数" :value="stats?.total ?? 0" />
        </a-card>
      </a-col>
    </a-row>

    <!-- 最新信号卡 -->
    <a-card title="各策略最新信号" style="margin-bottom: 16px" :loading="loading">
      <a-row :gutter="16">
        <a-col v-for="s in strategies" :key="s" :span="6">
          <a-card :bordered="true" size="small" class="sig-card">
            <div class="sig-title">{{ strategyNameMap[s] || s }}</div>
            <div class="sig-val" v-if="latest[s]">
              <template v-if="latest[s].payload?.position_temp != null">
                位置温度 <b>{{ Number(latest[s].payload.position_temp).toFixed(1) }}</b>
              </template>
              <template v-else-if="latest[s].payload?.heat != null">
                情绪热度 <b>{{ Number(latest[s].payload.heat).toFixed(2) }}</b>
              </template>
              <template v-else>
                <span class="muted">见趋势图</span>
              </template>
            </div>
            <div class="sig-sub" v-if="latest[s]">
              {{ latest[s].run_date }} ·
              <template v-if="latest[s].payload?.signal">{{ latest[s].payload.signal }}</template>
              <template v-else-if="latest[s].payload?.suggest_pos != null">
                仓位 {{ Number(latest[s].payload.suggest_pos * 100).toFixed(0) }}%
              </template>
            </div>
          </a-card>
        </a-col>
      </a-row>
      <a-empty v-if="!strategies.length" description="暂无策略数据，请先运行策略" />
    </a-card>

    <!-- 趋势图 -->
    <a-card title="历史趋势">
      <a-space style="margin-bottom: 16px">
        <span>选择策略：</span>
        <a-radio-group v-model:value="activeStrategy" button-style="solid">
          <a-radio-button v-for="s in strategies" :key="s" :value="s">
            {{ strategyNameMap[s] || s }}
          </a-radio-button>
        </a-radio-group>
      </a-space>
      <div ref="chartEl" style="height: 400px"></div>
    </a-card>
  </div>
</template>

<style scoped>
.sig-card {
  border-left: 3px solid #1677ff;
}
.sig-title {
  font-size: 13px;
  color: #888;
  margin-bottom: 6px;
}
.sig-val {
  font-size: 16px;
  margin-bottom: 4px;
}
.sig-val b {
  color: #1677ff;
}
.sig-sub {
  font-size: 12px;
  color: #999;
}
.muted {
  color: #bbb;
}
</style>
