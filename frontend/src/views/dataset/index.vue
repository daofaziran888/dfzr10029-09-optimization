<template>
  <section class="page" data-module="dataset">
    <header class="page-head">
      <div>
        <h2>数据集管理管理</h2>
        <p class="page-desc">维护分析数据集，围绕数据集编号、数据集名称、来源类型、字段数量做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">登记分析数据集</button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">导出数据集管理清单</button>
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
            <button
              class="link"
              type="button"
              :data-testid="`field-summary-${row.id}`"
              @click="openFieldSummary(row)"
            >
              字段摘要
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无数据集管理数据，可先登记分析数据集</td>
        </tr>
      </tbody>
    </table>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记分析数据集</h3>
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

    <div v-if="showFieldSummary" class="modal-backdrop" data-testid="field-summary-modal">
      <div class="modal field-summary-modal">
        <div class="page-head">
          <div>
            <h3>字段分区摘要 · {{ summaryDataset?.['数据集编号'] }}</h3>
            <p class="page-desc">
              当前版本 v{{ fieldSummary?.current_version ?? '—' }}，
              最近刷新 {{ fieldSummary?.refreshed_at ?? '—' }}；字段顺序由同一轮刷新确定，刷新间保持稳定。
            </p>
          </div>
          <button class="btn ghost" data-testid="close-field-summary" type="button" @click="showFieldSummary = false">关闭</button>
        </div>

        <div class="stat-row">
          <article class="stat-card">
            <span class="stat-label">分区总数</span>
            <strong class="stat-value" data-testid="summary-partition-total">{{ fieldSummary?.partition_summaries.length ?? 0 }}</strong>
          </article>
          <article class="stat-card">
            <span class="stat-label">本轮变化分区</span>
            <strong class="stat-value" data-testid="summary-changed-count">{{ fieldSummary?.changed_partitions.length ?? 0 }}</strong>
          </article>
          <article class="stat-card">
            <span class="stat-label">待核对项</span>
            <strong class="stat-value" data-testid="summary-pending-count">{{ fieldSummary?.pending_reconciles.length ?? 0 }}</strong>
          </article>
          <article class="stat-card">
            <span class="stat-label">字段总数</span>
            <strong class="stat-value">{{ fieldSummary?.field_order.length ?? 0 }}</strong>
          </article>
        </div>

        <div class="page-actions summary-toolbar">
          <button class="btn primary" data-testid="refresh-field-summary" type="button" :disabled="summaryLoading" @click="refreshSummary">
            {{ summaryLoading ? '刷新中…' : '刷新字段摘要' }}
          </button>
          <button class="btn" data-testid="toggle-changed-only" type="button" @click="changedOnly = !changedOnly">
            {{ changedOnly ? '查看全部分区' : '只看变化分区' }}
          </button>
          <button class="btn" data-testid="simulate-drift" type="button" :disabled="summaryLoading" @click="simulateDrift">
            模拟分区字段变化
          </button>
        </div>

        <h4>分区字段摘要（按当前版本排列）</h4>
        <table class="data-table" data-testid="partition-summary-table">
          <thead>
            <tr>
              <th>分区编号</th>
              <th>分区类型</th>
              <th>分区完成时间</th>
              <th>字段数</th>
              <th>本次变化</th>
              <th>字段顺序</th>
              <th>核对</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="part in visiblePartitions" :key="part['分区编号']" :data-testid="`partition-row-${part['分区编号']}`">
              <td>{{ part['分区编号'] }}</td>
              <td>{{ part['分区类型'] }}</td>
              <td>{{ part['分区完成时间'] }}</td>
              <td>{{ part.field_count }}</td>
              <td data-testid="partition-changes">
                <span v-if="!hasChanges(part)">无变化</span>
                <ul v-else class="change-list">
                  <li v-if="part.changes.lifecycle && part.changes.lifecycle !== '字段变化'">
                    分区{{ part.changes.lifecycle }}
                  </li>
                  <li v-if="part.changes.added.length">新增：{{ part.changes.added.join('、') }}</li>
                  <li v-if="part.changes.removed.length">移除：{{ part.changes.removed.join('、') }}</li>
                  <li v-for="item in part.changes.type_changed" :key="item['字段名称']">
                    类型变更：{{ item['字段名称'] }} {{ item['原类型'] }} → {{ item['新类型'] }}
                  </li>
                </ul>
              </td>
              <td class="field-order-cell" data-testid="partition-field-order">{{ part.field_order.join('、') }}</td>
              <td>
                <button
                  class="link"
                  type="button"
                  :data-testid="`reconcile-${part['分区编号']}`"
                  @click="reconcile(part['分区编号'], '核对通过')"
                >
                  核对通过
                </button>
              </td>
            </tr>
            <tr v-if="!visiblePartitions.length">
              <td colspan="7" class="empty-state">本轮没有发生变化的分区，切换为「查看全部分区」可浏览完整摘要</td>
            </tr>
          </tbody>
        </table>

        <h4>全局字段顺序（查询模板共享同一顺序）</h4>
        <div class="field-order-wrap" data-testid="global-field-order">
          <span v-for="(name, index) in fieldSummary?.field_order ?? []" :key="name" class="field-tag">
            {{ index + 1 }}. {{ name }}
          </span>
        </div>

        <h4>待核对项</h4>
        <table class="data-table" data-testid="pending-reconcile-table">
          <thead>
            <tr><th>核对编号</th><th>分区编号</th><th>版本</th><th>核对状态</th></tr>
          </thead>
          <tbody>
            <tr v-for="item in fieldSummary?.pending_reconciles ?? []" :key="item['核对编号']">
              <td>{{ item['核对编号'] }}</td>
              <td>{{ item['分区编号'] }}</td>
              <td>v{{ item['版本'] }}</td>
              <td>{{ item['核对状态'] }}</td>
            </tr>
            <tr v-if="!(fieldSummary?.pending_reconciles ?? []).length">
              <td colspan="4" class="empty-state">当前版本没有待核对项</td>
            </tr>
          </tbody>
        </table>

        <h4>保留版本（可回查）</h4>
        <div class="version-list" data-testid="version-list">
          <button
            v-for="version in summaryVersions"
            :key="version['版本']"
            class="btn"
            type="button"
            :data-testid="`version-${version['版本']}`"
            @click="loadVersion(version['版本'])"
          >
            v{{ version['版本'] }} · 变化分区 {{ version['变化分区数'] }} · {{ version.refreshed_at }}
          </button>
        </div>

        <footer class="page-foot">
          <span v-if="summaryMessage" data-testid="summary-message">{{ summaryMessage }}</span>
          <span v-if="summaryError" class="error-text" data-testid="summary-error">{{ summaryError }}</span>
        </footer>
      </div>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条数据集管理记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

type FieldChange = {
  lifecycle?: string
  added: string[]
  removed: string[]
  type_changed: { 字段名称: string; 原类型: string; 新类型: string }[]
}

type PartitionSummary = {
  分区编号: string
  分区类型: string
  分区完成时间: string
  field_order: string[]
  field_details?: { 字段名称: string; 字段类型: string }[]
  field_count: number
  signature: string
  last_change_seq: number
  last_refreshed_at: string
  changes: FieldChange
  分区状态?: string
}

type PendingReconcile = {
  核对编号: string
  分区编号: string
  版本: number
  核对状态: string
  变化摘要: FieldChange
}

type FieldSummaryView = {
  dataset_id: number
  current_version: number
  partition_summaries: PartitionSummary[]
  changed_partitions: PartitionSummary[]
  field_order: string[]
  pending_reconciles: PendingReconcile[]
  reconcile_history?: { 分区编号: string; 版本: number; 核对状态: string }[]
  refreshed_at: string | null
}

type SummaryVersion = { 版本: number; refreshed_at: string; 变化分区数: number }

const ENDPOINT = '/api/dataset'
const columns = ["数据集编号", "数据集名称", "来源类型", "字段数量", "行数估算", "刷新周期", "负责人", "数据集状态"]
const actions = ["完成接入", "启用数据集", "归档数据集"]
const statuses = ["待接入", "已接入", "使用中", "已归档"]
const metricNames = ["使用中数据集", "待接入数据集", "已归档数据集"]

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

// 字段分区摘要视图状态
const showFieldSummary = ref(false)
const summaryDataset = ref<Row | null>(null)
const fieldSummary = ref<FieldSummaryView | null>(null)
const summaryVersions = ref<SummaryVersion[]>([])
const changedOnly = ref(false)
const summaryLoading = ref(false)
const summaryMessage = ref('')
const summaryError = ref('')

const visiblePartitions = computed<PartitionSummary[]>(() => {
  if (!fieldSummary.value) return []
  return changedOnly.value
    ? fieldSummary.value.changed_partitions
    : fieldSummary.value.partition_summaries
})

function hasChanges(part: PartitionSummary): boolean {
  return part.changes.added.length > 0
    || part.changes.removed.length > 0
    || part.changes.type_changed.length > 0
}

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
    link.download = 'dataset.csv'
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
      throw new Error('数据集管理动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据集管理操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('分析数据集列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据集管理列表读取失败'
  }
}

// ------------------------------------------------- 字段分区摘要
async function openFieldSummary(row: Row) {
  summaryDataset.value = row
  showFieldSummary.value = true
  changedOnly.value = false
  summaryMessage.value = ''
  summaryError.value = ''
  await loadFieldSummary()
  await loadVersions()
}

async function loadFieldSummary(version?: number) {
  if (!summaryDataset.value) return
  summaryLoading.value = true
  summaryError.value = ''
  try {
    const suffix = version ? `/versions/${version}` : ''
    const response = await request(`${ENDPOINT}/${summaryDataset.value.id}/field-summary${suffix}`)
    if (!response.ok) throw new Error('字段分区摘要读取失败')
    fieldSummary.value = (await response.json()) as FieldSummaryView
    if (version) {
      summaryMessage.value = `正在回查 v${version} 历史版本，字段顺序为该版本归档顺序`
    } else {
      summaryMessage.value = ''
    }
  } catch (error) {
    summaryError.value = error instanceof Error ? error.message : '字段分区摘要读取失败'
  } finally {
    summaryLoading.value = false
  }
}

async function loadVersions() {
  if (!summaryDataset.value) return
  try {
    const response = await request(
      `${ENDPOINT}/${summaryDataset.value.id}/field-summary/versions`)
    if (!response.ok) throw new Error('版本清单读取失败')
    const payload = await response.json()
    summaryVersions.value = (payload.items ?? []) as SummaryVersion[]
  } catch (error) {
    summaryError.value = error instanceof Error ? error.message : '版本清单读取失败'
  }
}

async function refreshSummary() {
  if (!summaryDataset.value) return
  summaryLoading.value = true
  summaryError.value = ''
  summaryMessage.value = ''
  try {
    const response = await request(
      `${ENDPOINT}/${summaryDataset.value.id}/field-summary/refresh`, { method: 'POST' })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '刷新失败')
    fieldSummary.value = payload.entry as FieldSummaryView
    summaryMessage.value = payload.message
    await loadVersions()
  } catch (error) {
    summaryError.value = error instanceof Error ? error.message : '字段分区摘要刷新失败'
  } finally {
    summaryLoading.value = false
  }
}

async function reconcile(partitionId: string, result: string) {
  if (!summaryDataset.value) return
  summaryError.value = ''
  try {
    const response = await request(
      `${ENDPOINT}/${summaryDataset.value.id}/field-summary/reconcile`,
      { method: 'POST', body: JSON.stringify({ partition_id: partitionId, result }) })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '核对失败')
    summaryMessage.value = payload.message
    await loadFieldSummary()
  } catch (error) {
    summaryError.value = error instanceof Error ? error.message : '核对结果写入失败'
  }
}

async function loadVersion(version: number) {
  await loadFieldSummary(version)
}

async function simulateDrift() {
  if (!summaryDataset.value || !fieldSummary.value) return
  summaryLoading.value = true
  summaryError.value = ''
  // 取一个日分区，在其当前字段清单末尾追加两个字段，模拟外部数据源变化。
  const target = fieldSummary.value.partition_summaries.find(
    (part) => part.分区类型 === 'daily') ?? fieldSummary.value.partition_summaries[0]
  if (!target) {
    summaryError.value = '没有可模拟变化的分区'
    summaryLoading.value = false
    return
  }
  const stamp = new Date().toISOString().slice(0, 19).replace('T', ' ')
  const fields = [
    ...(target.field_details ?? target.field_order.map((name) => ({ 字段名称: name, 字段类型: 'string' }))),
    { 分区编号: target.分区编号, 分区类型: target.分区类型, 分区完成时间: target.分区完成时间,
      字段名称: `模拟字段_${stamp.slice(11, 19).replace(/:/g, '')}`, 字段类型: 'string' },
  ]
  try {
    const response = await request(
      `${ENDPOINT}/${summaryDataset.value.id}/field-summary/simulate-drift`,
      { method: 'POST', body: JSON.stringify({ fields }) })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '模拟变化失败')
    summaryMessage.value = '数据源分区字段已变化，点击「刷新字段摘要」后只重建该分区'
  } catch (error) {
    summaryError.value = error instanceof Error ? error.message : '模拟变化失败'
  } finally {
    summaryLoading.value = false
  }
}

onMounted(reload)
</script>

<style scoped>
.field-summary-modal {
  width: min(960px, 100%);
}
.summary-toolbar {
  margin: 8px 0 12px;
}
.change-list {
  margin: 0;
  padding-left: 16px;
}
.field-order-cell {
  max-width: 260px;
  font-size: 12px;
}
.field-order-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px;
}
.field-tag {
  background: #eef4ff;
  border: 1px solid #c7dbff;
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 12px;
  white-space: nowrap;
}
.version-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
h4 {
  margin: 16px 0 8px;
}
</style>
