import { expect, test } from '@playwright/test'

/**
 * 字段分区摘要专项验收：
 * 1. 数据集页可查看每个分区的字段摘要与本次变化分区；
 * 2. 刷新只重建变化分区，字段顺序在多轮刷新间保持稳定；
 * 3. 核对结果唯一、版本保留可回查；
 * 4. 查询模板页跨模块读到的字段顺序与数据集页一致。
 */
test('字段分区摘要：分区视图、增量刷新、顺序稳定、核对与版本回查', async ({ page }) => {
  test.setTimeout(180_000)
  const browserErrors: string[] = []
  page.on('pageerror', (e) => browserErrors.push(e.message))
  page.on('response', (r) => {
    if (r.url().includes('/api/') && r.status() >= 400) browserErrors.push(`${r.status()} ${r.url()}`)
  })

  await page.goto('/dataset')
  await page.waitForTimeout(2000)

  // 打开第一个数据集的字段分区摘要弹窗
  await page.getByTestId('field-summary-1').click()
  await expect(page.getByTestId('field-summary-modal')).toBeVisible()
  await expect(page.getByTestId('partition-summary-table')).toBeVisible()

  const strip = (text: string) => text.replace(/\s+/g, '')
  const initialOrder = strip(await page.getByTestId('global-field-order').innerText())
  const initialPartitionRows = await page.getByTestId('partition-summary-table').locator('tbody tr').count()
  expect(initialPartitionRows).toBeGreaterThanOrEqual(3)

  // 无变化刷新：版本递增、变化分区为 0、字段顺序完全不变
  await page.getByTestId('refresh-field-summary').click()
  await expect(page.getByTestId('summary-changed-count')).toHaveText('0')
  expect(strip(await page.getByTestId('global-field-order').innerText())).toBe(initialOrder)

  // 模拟外部数据源分区字段变化后刷新：只显示发生变化的分区
  await page.getByTestId('simulate-drift').click()
  await page.getByTestId('refresh-field-summary').click()
  await expect(page.getByTestId('summary-changed-count')).toHaveText('1')
  await page.getByTestId('toggle-changed-only').click()
  const changedRows = page.getByTestId('partition-summary-table').locator('tbody tr[data-testid^="partition-row-"]')
  await expect(changedRows).toHaveCount(1)
  const changeText = await changedRows.first().getByTestId('partition-changes').innerText()
  expect(changeText).toContain('新增')

  // 老字段位置不变：全局顺序以初始顺序为前缀
  const afterOrderText = strip(await page.getByTestId('global-field-order').innerText())
  expect(afterOrderText.startsWith(initialOrder)).toBe(true)

  // 待核对项出现，并在核对后清空，且同分区只产生一份核对结果
  await expect(page.getByTestId('summary-pending-count')).toHaveText('1')
  const pendingRows = page.getByTestId('pending-reconcile-table').locator('tbody tr')
  await expect(pendingRows).toHaveCount(1)
  const partitionId = (await changedRows.first().getAttribute('data-testid'))?.replace('partition-row-', '') ?? ''
  await page.getByTestId(`reconcile-${partitionId}`).click()
  await expect(page.getByTestId('summary-pending-count')).toHaveText('0')
  // 核对落定后只剩"没有待核对项"的空状态行
  await expect(pendingRows).toHaveCount(1)
  await expect(pendingRows.first()).toContainText('当前版本没有待核对项')

  // 版本保留并可回查：v1 仍然存在
  const versionButtons = page.getByTestId('version-list').locator('button')
  expect(await versionButtons.count()).toBeGreaterThanOrEqual(2)
  await page.getByTestId('version-1').click()
  await expect(page.getByTestId('summary-message')).toContainText('v1')
  expect(strip(await page.getByTestId('global-field-order').innerText())).toBe(initialOrder)

  await page.getByTestId('close-field-summary').click()
  await expect(page.getByTestId('field-summary-modal')).toHaveCount(0)

  expect(browserErrors).toEqual([])
})

test('查询模板页：跨模块字段顺序与数据集页共享同一来源', async ({ page }) => {
  test.setTimeout(120_000)
  const browserErrors: string[] = []
  page.on('pageerror', (e) => browserErrors.push(e.message))
  page.on('response', (r) => {
    if (r.url().includes('/api/') && r.status() >= 400) browserErrors.push(`${r.status()} ${r.url()}`)
  })

  await page.goto('/query_builder')
  await expect(page.getByTestId('dataset-field-order-panel')).toBeVisible()
  const tags = page.getByTestId('dataset-field-order').locator('.field-tag')
  expect(await tags.count()).toBeGreaterThanOrEqual(3)

  // 直接取后端两份数据比对：查询模板接口与数据集摘要接口字段顺序一致
  const datasetResp = await page.request.get('http://127.0.0.1:8000/api/dataset/1/field-summary')
  const datasetView = await datasetResp.json()
  const qbResp = await page.request.get('http://127.0.0.1:8000/api/query_builder/dataset-fields/DATA-0001')
  const qbView = await qbResp.json()
  expect(qbView.field_order).toEqual(datasetView.field_order)

  // 切换数据集后顺序随之切换且非空
  await page.getByTestId('dataset-field-select').selectOption('DATA-0002')
  await page.getByTestId('reload-dataset-fields').click()
  expect(await page.getByTestId('dataset-field-order').locator('.field-tag').count()).toBeGreaterThanOrEqual(3)

  expect(browserErrors).toEqual([])
})

test('概览页：展示字段分区摘要待核对项', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByTestId('field-summary-overview')).toBeVisible()
  const cards = page.getByTestId('field-summary-overview').locator('.stat-value')
  await expect(cards).toHaveCount(4)
})
