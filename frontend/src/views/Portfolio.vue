<script setup>
import { ref, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { PlusOutlined, ReloadOutlined, DeleteOutlined } from '@ant-design/icons-vue'
import { getQuotes, addPosition, deletePosition, clearPositions } from '../api'

const loading = ref(false)
const summary = ref(null)
const positions = ref([])
const modalOpen = ref(false)
const saving = ref(false)
const form = ref({ code: '', name: '', cost: null, shares: null, bought_at: '', note: '' })

const columns = [
  { title: '代码', dataIndex: 'code', key: 'code', width: 100 },
  { title: '名称', dataIndex: 'name', key: 'name', width: 100 },
  { title: '成本价', dataIndex: 'cost', key: 'cost', align: 'right', width: 90 },
  { title: '现价', dataIndex: 'price', key: 'price', align: 'right', width: 90 },
  { title: '当日涨跌', key: 'pct', align: 'right', width: 90 },
  { title: '数量', dataIndex: 'shares', key: 'shares', align: 'right', width: 80 },
  { title: '市值', dataIndex: 'market_value', key: 'mv', align: 'right', width: 110 },
  { title: '浮动盈亏', key: 'pnl', align: 'right', width: 120 },
  { title: '盈亏比', key: 'pnl_pct', align: 'right', width: 90 },
  { title: '仓位占比', key: 'weight', width: 120 },
  { title: '操作', key: 'op', width: 80, fixed: 'right' },
]

function fmt(n) {
  return n == null ? '-' : Number(n).toFixed(2)
}
function pctClass(v) {
  if (v > 0) return 'up'
  if (v < 0) return 'down'
  return ''
}
function signed(v, suffix = '') {
  if (v == null) return '-'
  return (v > 0 ? '+' : '') + Number(v).toFixed(2) + suffix
}

async function refresh() {
  loading.value = true
  try {
    const d = await getQuotes()
    summary.value = d.summary
    positions.value = d.positions
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = false
  }
}

function openModal() {
  form.value = { code: '', name: '', cost: null, shares: null, bought_at: '', note: '' }
  modalOpen.value = true
}

async function save() {
  if (!form.value.code || !form.value.cost || !form.value.shares) {
    message.warning('请填写代码、成本价和数量')
    return
  }
  saving.value = true
  try {
    await addPosition(form.value)
    message.success('已保存')
    modalOpen.value = false
    refresh()
  } catch (e) {
    message.error(e.message)
  } finally {
    saving.value = false
  }
}

async function remove(rec) {
  await deletePosition(rec.code)
  message.success('已删除')
  refresh()
}

async function clearAll() {
  await clearPositions()
  message.success('已清空')
  refresh()
}

onMounted(refresh)
</script>

<template>
  <div>
    <!-- 汇总卡片 -->
    <a-row :gutter="16" style="margin-bottom: 16px">
      <a-col :span="4">
        <a-card>
          <a-statistic title="总市值" :value="summary?.market_value ?? 0" :precision="0" prefix="¥" />
        </a-card>
      </a-col>
      <a-col :span="4">
        <a-card>
          <a-statistic title="总成本" :value="summary?.cost ?? 0" :precision="0" prefix="¥" />
        </a-card>
      </a-col>
      <a-col :span="4">
        <a-card>
          <a-statistic
            title="浮动盈亏"
            :value="summary?.pnl ?? 0"
            :precision="0"
            prefix="¥"
            :value-style="{ color: (summary?.pnl ?? 0) >= 0 ? '#f5222d' : '#52c41a' }"
          />
        </a-card>
      </a-col>
      <a-col :span="4">
        <a-card>
          <a-statistic
            title="盈亏比例"
            :value="summary?.pnl_pct ?? 0"
            :precision="2"
            suffix="%"
            :value-style="{ color: (summary?.pnl_pct ?? 0) >= 0 ? '#f5222d' : '#52c41a' }"
          />
        </a-card>
      </a-col>
      <a-col :span="4">
        <a-card>
          <a-statistic
            title="当日盈亏"
            :value="summary?.day_pnl ?? 0"
            :precision="0"
            prefix="¥"
            :value-style="{ color: (summary?.day_pnl ?? 0) >= 0 ? '#f5222d' : '#52c41a' }"
          />
        </a-card>
      </a-col>
      <a-col :span="4">
        <a-card>
          <a-statistic title="持仓数量" :value="summary?.count ?? 0" />
        </a-card>
      </a-col>
    </a-row>

    <!-- 操作栏 -->
    <a-card style="margin-bottom: 16px">
      <a-space>
        <a-button type="primary" @click="openModal">
          <template #icon><PlusOutlined /></template>
          添加持仓
        </a-button>
        <a-button @click="refresh">
          <template #icon><ReloadOutlined /></template>
          刷新行情
        </a-button>
        <a-popconfirm title="确定清空全部持仓？" @confirm="clearAll">
          <a-button danger>
            <template #icon><DeleteOutlined /></template>
            清空
          </a-button>
        </a-popconfirm>
      </a-space>
    </a-card>

    <!-- 持仓表格 -->
    <a-card>
      <a-table
        :columns="columns"
        :data-source="positions"
        :loading="loading"
        row-key="code"
        size="middle"
        :pagination="false"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'pct'">
            <span :class="pctClass(record.pct)">{{ signed(record.pct, '%') }}</span>
          </template>
          <template v-else-if="column.key === 'pnl'">
            <span :class="pctClass(record.pnl)">{{ signed(record.pnl) }}</span>
          </template>
          <template v-else-if="column.key === 'pnl_pct'">
            <span :class="pctClass(record.pnl_pct)">{{ signed(record.pnl_pct, '%') }}</span>
          </template>
          <template v-else-if="column.key === 'weight'">
            <a-progress :percent="Number(record.weight ?? 0)" :size="'small'" :stroke-color="'#1677ff'" />
          </template>
          <template v-else-if="column.key === 'op'">
            <a-popconfirm title="确定删除？" @confirm="remove(record)">
              <a-button type="link" danger size="small">删除</a-button>
            </a-popconfirm>
          </template>
        </template>
      </a-table>
    </a-card>

    <!-- 新增/编辑弹窗 -->
    <a-modal v-model:open="modalOpen" title="添加持仓" :confirm-loading="saving" @ok="save">
      <a-form :model="form" layout="vertical">
        <a-form-item label="股票代码" required>
          <a-input v-model:value="form.code" placeholder="如 600519 / sz000858" />
        </a-form-item>
        <a-form-item label="名称（可选）">
          <a-input v-model:value="form.name" placeholder="如 贵州茅台" />
        </a-form-item>
        <a-form-item label="成本价（元/股）" required>
          <a-input-number v-model:value="form.cost" :min="0.01" :step="0.01" style="width: 100%" />
        </a-form-item>
        <a-form-item label="数量（股）" required>
          <a-input-number v-model:value="form.shares" :min="1" :step="100" style="width: 100%" />
        </a-form-item>
        <a-form-item label="买入日期">
          <a-input v-model:value="form.bought_at" placeholder="2026-11-02" />
        </a-form-item>
        <a-form-item label="备注">
          <a-textarea v-model:value="form.note" :rows="2" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>
