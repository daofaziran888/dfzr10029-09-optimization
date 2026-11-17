"""OLAP查询业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.services.field_summary import field_summary_service
from app.store import store

MODULE = "query_builder"
DATASET_MODULE = "dataset"
LIST_FIELDS = ["模板编号", "模板名称", "查询语句", "参数定义", "数据集范围", "超时秒数", "缓存策略", "模板状态"]
REQUIRED_FIELDS = ["模板编号", "模板名称", "查询语句"]
STATUS_ORDER = ["草稿", "已保存", "已发布", "已停用"]
ACTION_RULES = {"保存模板": "已保存", "发布模板": "已发布", "停用模板": "已停用"}
NEGATIVE_ACTIONS = ["停用模板"]


class QueryBuilderService:
    def list_entries(
        self,
        *,
        filters: dict[str, str] | None = None,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        for field, expected in (filters or {}).items():
            rows = [row for row in rows if expected.casefold() in str(row.get(field, "")).casefold()]
        if keyword:
            rows = [row for row in rows if keyword.casefold() in str(row.get("模板编号", "")).casefold()]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in LIST_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"查询模板 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于OLAP查询可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"查询模板已{action}"

    # ------------------------------------------- 跨模块读取字段分区摘要
    def dataset_field_order(self, dataset_code: str) -> dict[str, Any]:
        """顺着既有取数调用关系，跨模块读取数据集字段分区摘要的稳定字段顺序。

        与数据集页面共用 field_summary_service 同一份来源记录，查询模板看到的
        字段顺序不会因刷新而重排；找不到对应数据集时返回空顺序并说明原因，
        兼容既有业务边界而不是抛异常打断模板页面。
        """
        dataset_id = field_summary_service.resolve_id_by_code(dataset_code)
        if dataset_id is None:
            # 兼容旧数据：模板的数据集范围可能还是示例文本，没有接入摘要视图。
            return {
                "数据集编号": dataset_code,
                "current_version": None,
                "field_order": [],
                "message": "该数据集尚未接入字段分区摘要，返回空字段顺序",
            }
        view = field_summary_service.get_view(dataset_id)
        if view is None:
            return {
                "数据集编号": dataset_code,
                "current_version": None,
                "field_order": [],
                "message": "字段分区摘要尚未生成",
            }
        return {
            "数据集编号": dataset_code,
            "current_version": view["current_version"],
            "field_order": view["field_order"],
            "partition_summaries": [
                {
                    "分区编号": item["分区编号"],
                    "field_order": item["field_order"],
                    "field_count": item["field_count"],
                }
                for item in view["partition_summaries"]
            ],
        }
