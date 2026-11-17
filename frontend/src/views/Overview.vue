<template>
  <section class="page">
    <header class="page-head">
      <div>
        <h2>运营概览</h2>
        <p class="page-desc">汇总各业务模块的关键指标，先看总量再看异常。</p>
      </div>
    </header>
    <div class="stat-row">
      <article v-for="card in cards" :key="card.label" class="stat-card">
        <span class="stat-label">{{ card.label }}</span>
        <strong class="stat-value">{{ card.value }}</strong>
      </article>
    </div>
    <table class="data-table">
      <thead>
        <tr><th>业务模块</th><th>今日新增</th><th>待处理</th><th>异常量</th></tr>
      </thead>
      <tbody>
        <tr v-for="row in moduleRows" :key="row.name">
          <td>{{ row.name }}</td>
          <td>{{ row.created }}</td>
          <td>{{ row.pending }}</td>
          <td>{{ row.abnormal }}</td>
        </tr>
      </tbody>
    </table>

    <header class="page-head" style="margin-top: 16px;">
      <div>
        <h3>字段分区摘要概览</h3>
        <p class="page-desc">按当前版本汇总各数据集的分区摘要与待核对项，与数据集页面共用同一份来源记录。</p>
      </div>
    </header>
    <div class="stat-row" data-testid="field-summary-overview">
      <article v-for="card in fieldSummaryCards" :key="card.label" class="stat-card">
        <span class="stat-label">{{ card.label }}</span>
        <strong class="stat-value">{{ card.value }}</strong>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { fetchJson } from '@/api/client'

type Overview = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
  field_summary?: FieldSummaryOverview
}

type FieldSummaryOverview = {
  摘要数据集: number
  分区总数: number
  本轮变化分区: number
  待核对项: number
}

const cards = ref<Overview['cards']>([])
const moduleRows = ref<Overview['modules']>([])
const fieldSummary = ref<FieldSummaryOverview>({ 摘要数据集: 0, 分区总数: 0, 本轮变化分区: 0, 待核对项: 0 })

const fieldSummaryCards = computed(() => [
  { label: '摘要数据集', value: fieldSummary.value.摘要数据集 },
  { label: '分区总数', value: fieldSummary.value.分区总数 },
  { label: '本轮变化分区', value: fieldSummary.value.本轮变化分区 },
  { label: '待核对项', value: fieldSummary.value.待核对项 },
])

onMounted(async () => {
  try {
    const payload = await fetchJson<Overview>('/api/overview')
    cards.value = payload.cards
    moduleRows.value = payload.modules
    if (payload.field_summary) fieldSummary.value = payload.field_summary
  } catch {
    cards.value = [{"label": "业务模块", "value": 0}, {"label": "今日新增", "value": 0}]
    moduleRows.value = [{"name": "指标定义", "created": 0, "pending": 0, "abnormal": 0}, {"name": "维度管理", "created": 0, "pending": 0, "abnormal": 0}, {"name": "数据集管理", "created": 0, "pending": 0, "abnormal": 0}, {"name": "分析实验", "created": 0, "pending": 0, "abnormal": 0}, {"name": "OLAP查询", "created": 0, "pending": 0, "abnormal": 0}, {"name": "数据看板", "created": 0, "pending": 0, "abnormal": 0}, {"name": "图表配置", "created": 0, "pending": 0, "abnormal": 0}, {"name": "数据API发布", "created": 0, "pending": 0, "abnormal": 0}, {"name": "智能告警", "created": 0, "pending": 0, "abnormal": 0}, {"name": "分析用户组", "created": 0, "pending": 0, "abnormal": 0}, {"name": "数据快照", "created": 0, "pending": 0, "abnormal": 0}, {"name": "任务调度", "created": 0, "pending": 0, "abnormal": 0}, {"name": "缓存管理", "created": 0, "pending": 0, "abnormal": 0}, {"name": "分析管道", "created": 0, "pending": 0, "abnormal": 0}, {"name": "分析模型", "created": 0, "pending": 0, "abnormal": 0}, {"name": "数据集市", "created": 0, "pending": 0, "abnormal": 0}, {"name": "数据导出", "created": 0, "pending": 0, "abnormal": 0}, {"name": "数据审计", "created": 0, "pending": 0, "abnormal": 0}]
  }
})
</script>
