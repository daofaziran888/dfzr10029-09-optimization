<template>
  <section class="page" data-module="query_builder">
    <header class="page-head">
      <div>
        <h2>OLAP查询管理</h2>
        <p class="page-desc">维护查询模板，围绕模板编号、模板名称、查询语句、参数定义做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">登记查询模板</button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">导出OLAP查询清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :data-testid="`row-${row.id}`" :data-status="String(row.status)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              :data-testid="`action-${row.id}-${action}`"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无OLAP查询数据，可先登记查询模板</td>
        </tr>
      </tbody>
    </table>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记查询模板</h3>
        <label v-for="field in columns" :key="field" class="create-field">
          <span>{{ field }}</span>
          <input v-model="createValues[field]" :data-testid="`create-${field}`" required />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <section class="field-order-panel" data-testid="dataset-field-order-panel">
      <header class="page-head">
        <div>
          <h3>数据集字段顺序</h3>
          <p class="page-desc">跨模块读取字段分区摘要的同一份来源记录，查询模板看到的字段顺序与数据集页面保持稳定一致。</p>
        </div>
        <div class="page-actions">
          <select v-model="selectedDataset" data-testid="dataset-field-select" @change="loadDatasetFields">
            <option v-for="option in datasetOptions" :key="option.code" :value="option.code">
              {{ option.code }}（{{ option.name }}）
            </option>
          </select>
          <button class="btn" data-testid="reload-dataset-fields" type="button" @click="loadDatasetFields">重新读取</button>
        </div>
      </header>
      <p v-if="datasetFieldMessage" class="page-desc">{{ datasetFieldMessage }}</p>
      <div class="field-order-wrap" data-testid="dataset-field-order">
        <span v-for="(name, index) in datasetFieldOrder" :key="name" class="field-tag">
          {{ index + 1 }}. {{ name }}
        </span>
        <span v-if="!datasetFieldOrder.length" class="empty-state">该数据集暂无字段顺序记录</span>
      </div>
      <p class="page-desc" v-if="datasetFieldVersion">
        来源版本：v{{ datasetFieldVersion }}，与数据集页面字段分区摘要当前版本一致
      </p>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条OLAP查询记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/query_builder'
const columns = ["模板编号", "模板名称", "查询语句", "参数定义", "数据集范围", "超时秒数", "缓存策略", "模板状态"]
const actions = ["保存模板", "发布模板", "停用模板"]
const statuses = ["草稿", "已保存", "已发布", "已停用"]
const metricNames = ["已发布模板", "草稿模板", "停用模板"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})
const stats = computed(() => [
  { label: metricNames[0], value: total.value },
  { label: metricNames[1], value: rows.value.filter((row) => row.status === statuses[1]).length },
  { label: metricNames[2], value: rows.value.filter((row) => row.status === statuses[statuses.length - 1]).length },
])

function resetFilters() {
  filters.value = {}
  void reload()
}

async function exportRows() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value).toString()
  try {
    const response = await request(`${ENDPOINT}/export?${query}`)
    if (!response.ok) throw new Error('导出失败，请稍后重试')
    const url = URL.createObjectURL(await response.blob())
    const link = document.createElement('a')
    link.href = url
    link.download = 'query_builder.csv'
    link.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate() {
  createValues.value = Object.fromEntries(columns.map((field) => [field, '']))
  errorMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true
  errorMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST', body: JSON.stringify(createValues.value),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '登记失败')
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('OLAP查询动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'OLAP查询操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('查询模板列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'OLAP查询列表读取失败'
  }
}

// 跨模块读取数据集字段分区摘要，字段顺序与数据集页面共享同一来源。
const datasetOptions = [
  { code: 'DATA-0001', name: '数据集管理样例1' },
  { code: 'DATA-0002', name: '数据集管理样例2' },
  { code: 'DATA-0003', name: '数据集管理样例3' },
]
const selectedDataset = ref(datasetOptions[0].code)
const datasetFieldOrder = ref<string[]>([])
const datasetFieldVersion = ref<number | null>(null)
const datasetFieldMessage = ref('')

async function loadDatasetFields() {
  datasetFieldMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/dataset-fields/${encodeURIComponent(selectedDataset.value)}`)
    if (!response.ok) throw new Error('字段分区摘要读取失败')
    const payload = await response.json()
    datasetFieldOrder.value = payload.field_order ?? []
    datasetFieldVersion.value = payload.current_version ?? null
    datasetFieldMessage.value = payload.message ?? ''
  } catch (error) {
    datasetFieldMessage.value = error instanceof Error ? error.message : '字段分区摘要读取失败'
    datasetFieldOrder.value = []
  }
}

onMounted(() => {
  void reload()
  void loadDatasetFields()
})
</script>

<style scoped>
.field-order-panel {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 12px;
}
.field-order-panel select {
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 13px;
}
.field-order-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 8px 0;
}
.field-tag {
  background: #eef4ff;
  border: 1px solid #c7dbff;
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 12px;
  white-space: nowrap;
}
</style>
