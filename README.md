# 数据分析实验与数据应用服务平台

面向指标口径管理、分析实验设计、OLAP查询、数据看板构建与数据API发布的数据应用平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 指标定义 | `metric_def` | 指标 | 指标编号、指标名称、计算公式 |
| 维度管理 | `dimension` | 分析维度 | 维度编号、维度名称、维度类型 |
| 数据集管理 | `dataset` | 分析数据集 | 数据集编号、数据集名称、来源类型 |
| 分析实验 | `experiment` | 实验方案 | 方案编号、实验名称、分析数据集 |
| OLAP查询 | `query_builder` | 查询模板 | 模板编号、模板名称、查询语句 |
| 数据看板 | `dashboard` | 看板配置 | 看板编号、看板名称、包含图表 |
| 图表配置 | `chart` | 图表 | 图表编号、图表名称、图表类型 |
| 数据API发布 | `data_service` | 数据服务 | 服务编号、服务名称、输出数据集 |
| 智能告警 | `alert` | 告警规则 | 规则编号、告警名称、监控指标 |
| 分析用户组 | `user_group` | 用户组 | 组编号、组名称、组描述 |
| 数据快照 | `snapshot` | 快照记录 | 快照编号、数据集名称、快照时间 |
| 任务调度 | `scheduler` | 调度任务 | 任务编号、任务名称、调度类型 |
| 缓存管理 | `cache` | 缓存配置 | 缓存编号、缓存目标、缓存策略 |
| 分析管道 | `pipeline` | 分析节点 | 节点编号、输入数据集、分析算子 |
| 分析模型 | `model` | 模型配置 | 模型编号、模型名称、模型类型 |
| 数据集市 | `data_mart` | 集市表 | 表编号、表名称、主题域 |
| 数据导出 | `export` | 导出任务 | 任务编号、导出对象、导出格式 |
| 数据审计 | `audit` | 审计记录 | 记录编号、操作类型、操作人 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 字段分区摘要（数据集管理）

数据集字段清单不再每次刷新都整批重建，而是维护分区字段摘要视图，核心实现见
`backend/app/services/field_summary.py`（进程级单例，数据集页面、查询模板、运营概览
共享同一份来源记录）：

- **只刷新变化分区**：按分区读取当前字段清单并计算内容签名，签名未变的分区沿用上一版
  摘要，只有字段变化、分区新建/下线/重新上线的分区才重建并出现在 `changed_partitions`。
- **字段顺序稳定**：全局字段注册表记录字段首次出现的位置，新字段只追加队尾，老字段位置
  永久不变；分区摘要顺序同样沿用既有出现顺序。
- **同一轮原子提交**：分区摘要与字段顺序在同一次刷新内于临时视图加工，完成后一次性替换
  可见状态，每次提交只生成一个自增版本，旧版本整体归档可回查，当前有效版本始终唯一。
- **核对结果唯一**：变化分区按当前版本生成待核对项，同分区同版本重复或冲突核对只保留
  一份有效结果，概览页汇总待核对量。

接口契约（均挂在数据集路由下）：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/dataset/{id}/field-summary?changed_only=` | 字段契约接口，按当前版本返回分区摘要视图 |
| POST | `/api/dataset/{id}/field-summary/refresh` | 读取当前数据、汇总变化分区并重建摘要，提交新版本 |
| GET | `/api/dataset/{id}/field-summary/versions` | 保留版本清单 |
| GET | `/api/dataset/{id}/field-summary/versions/{version}` | 按版本回查摘要 |
| POST | `/api/dataset/{id}/field-summary/reconcile` | 写入分区核对结果（核对通过/核对驳回/冲突待裁决） |
| POST | `/api/dataset/{id}/field-summary/simulate-drift` | 联调钩子，模拟外部数据源分区字段变化 |

查询模板通过 `GET /api/query_builder/dataset-fields/{数据集编号}` 跨模块读取同一来源的
稳定字段顺序；未接入摘要的旧数据集返回空顺序与说明，不打断既有页面。

验收脚本：`backend/tests/test_field_summary_edge.py`（服务级边界场景）、
`frontend/tests/field-summary.spec.ts`（端到端验收）。

领域：数据工程
子方向：数据分析与数据应用
