<script setup>
import { ref, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { PlusOutlined } from '@ant-design/icons-vue'
import { getTrades, addTrade, updateTrade, deleteTrade } from '../api'

const loading = ref(false)
const trades = ref([])
const stats = ref(null)
const modalOpen = ref(false)
const saving = ref(false)
const editingId = ref(null)

const emptyForm = () => ({
  code: '', name: '', direction: 'buy', trade_date: '',
  price: null, shares: null, reason: '', review: '', tags: [], note: '',
})
const form = ref(emptyForm())

const columns = [
  { title: '日期', dataIndex: 'trade_date', key: 'date', width: 110 },
  { title: '方向', dataIndex: 'direction', key: 'dir', width: 80 },
  { title: '代码', dataIndex: 'code', key: 'code', width: 90 },
  { title: '名称', dataIndex: 'name', key: 'name', width: 100 },
  { title: '价格', dataIndex: 'price', key: 'price', align: 'right', width: 90 },
  { title: '数量', dataIndex: 'shares', key: 'shares', align: 'right', width: 80 },
  { title: '金额', dataIndex: 'amount', key: 'amount', align: 'right', width: 110 },
  { title: '交易原因', dataIndex: 'reason', key: 'reason' },
  { title: '事后复盘', dataIndex: 'review', key: 'review' },
  { title: '标签', key: 'tags', width: 140 },
  { title: '操作', key: 'op', width: 120, fixed: 'right' },
]

async function load() {
  loading.value = true
  try {
    const d = await getTrades()
    trades.value = d.trades
    stats.value = d.stats
  } catch (e) {
    message.error(e.message)
  } finally {
    loading.value = false
  }
}

function openAdd() {
  editingId.value = null
  form.value = emptyForm()
  modalOpen.value = true
}

function openEdit(rec) {
  editingId.value = rec.id
  form.value = {
    code: rec.code, name: rec.name, direction: rec.direction, trade_date: rec.trade_date,
    price: rec.price, shares: rec.shares, reason: rec.reason, review: rec.review,
    tags: rec.tags || [], note: rec.note || '',
  }
  modalOpen.value = true
}

async function save() {
  if (!form.value.code || !form.value.price || !form.value.shares) {
    message.warning('请填写代码、价格和数量')
    return
  }
  saving.value = true
  try {
    if (editingId.value) {
      await updateTrade(editingId.value, form.value)
    } else {
      await addTrade(form.value)
    }
    message.success('已保存')
    modalOpen.value = false
    load()
  } catch (e) {
    message.error(e.message)
  } finally {
    saving.value = false
  }
}

async function remove(rec) {
  await deleteTrade(rec.id)
  message.success('已删除')
  load()
}

onMounted(load)
</script>

<template>
  <div>
    <a-row :gutter="16" style="margin-bottom: 16px">
      <a-col :span="6">
        <a-card><a-statistic title="总笔数" :value="stats?.total ?? 0" /></a-card>
      </a-col>
      <a-col :span="6">
        <a-card>
          <a-statistic title="买入笔数" :value="stats?.buy_count ?? 0" :value-style="{ color: '#f5222d' }" />
        </a-card>
      </a-col>
      <a-col :span="6">
        <a-card>
          <a-statistic title="卖出笔数" :value="stats?.sell_count ?? 0" :value-style="{ color: '#52c41a' }" />
        </a-card>
      </a-col>
      <a-col :span="6">
        <a-card>
          <a-statistic title="净买入金额" :value="stats?.net_amount ?? 0" :precision="0" prefix="¥" />
        </a-card>
      </a-col>
    </a-row>

    <a-card>
      <a-space style="margin-bottom: 16px">
        <a-button type="primary" @click="openAdd">
          <template #icon><PlusOutlined /></template>
          记录一笔交易
        </a-button>
      </a-space>

      <a-table
        :columns="columns"
        :data-source="trades"
        :loading="loading"
        row-key="id"
        size="middle"
        :pagination="{ pageSize: 20 }"
      >
        <template #bodyCell="{ column, record }">
          <template v-if="column.key === 'dir'">
            <a-tag :color="record.direction === 'buy' ? 'red' : 'green'">
              {{ record.direction_cn }}
            </a-tag>
          </template>
          <template v-else-if="column.key === 'reason'">
            <div class="reason">{{ record.reason || '—' }}</div>
          </template>
          <template v-else-if="column.key === 'review'">
            <div class="review">{{ record.review || '—' }}</div>
          </template>
          <template v-else-if="column.key === 'tags'">
            <a-tag v-for="t in record.tags || []" :key="t" color="blue">{{ t }}</a-tag>
          </template>
          <template v-else-if="column.key === 'op'">
            <a-space>
              <a-button type="link" size="small" @click="openEdit(record)">编辑</a-button>
              <a-popconfirm title="确定删除？" @confirm="remove(record)">
                <a-button type="link" danger size="small">删除</a-button>
              </a-popconfirm>
            </a-space>
          </template>
        </template>
      </a-table>
    </a-card>

    <a-modal
      v-model:open="modalOpen"
      :title="editingId ? '编辑交易' : '记录交易'"
      :confirm-loading="saving"
      @ok="save"
      width="560"
    >
      <a-form :model="form" layout="vertical">
        <a-row :gutter="16">
          <a-col :span="8">
            <a-form-item label="方向" required>
              <a-select v-model:value="form.direction">
                <a-select-option value="buy">买入</a-select-option>
                <a-select-option value="sell">卖出</a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item label="代码" required>
              <a-input v-model:value="form.code" placeholder="600519" />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item label="名称">
              <a-input v-model:value="form.name" placeholder="贵州茅台" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-row :gutter="16">
          <a-col :span="8">
            <a-form-item label="日期">
              <a-input v-model:value="form.trade_date" placeholder="2026-11-02" />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item label="价格" required>
              <a-input-number v-model:value="form.price" :min="0.01" style="width: 100%" />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item label="数量" required>
              <a-input-number v-model:value="form.shares" :min="1" :step="100" style="width: 100%" />
            </a-form-item>
          </a-col>
        </a-row>
        <a-form-item label="交易原因（重点记录）">
          <a-textarea v-model:value="form.reason" :rows="3" placeholder="为什么买/卖？当时的判断依据" />
        </a-form-item>
        <a-form-item label="事后复盘">
          <a-textarea v-model:value="form.review" :rows="2" placeholder="这笔交易做对了吗？" />
        </a-form-item>
        <a-form-item label="标签">
          <a-select v-model:value="form.tags" mode="tags" placeholder="如：价值投资、止盈、追高" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<style scoped>
.reason {
  background: #f6f6f6;
  padding: 6px 10px;
  border-radius: 4px;
  color: #555;
}
.review {
  background: #fff7e6;
  padding: 6px 10px;
  border-radius: 4px;
  color: #ad6800;
}
</style>
