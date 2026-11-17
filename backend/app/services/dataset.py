"""数据集管理业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.services.field_summary import RECONCILE_RESULTS, field_summary_service
from app.store import store

MODULE = "dataset"
LIST_FIELDS = ["数据集编号", "数据集名称", "来源类型", "字段数量", "行数估算", "刷新周期", "负责人", "数据集状态"]
REQUIRED_FIELDS = ["数据集编号", "数据集名称", "来源类型"]
STATUS_ORDER = ["待接入", "已接入", "使用中", "已归档"]
ACTION_RULES = {"完成接入": "已接入", "启用数据集": "使用中", "归档数据集": "已归档"}
NEGATIVE_ACTIONS = []


class DatasetService:
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
            rows = [row for row in rows if keyword.casefold() in str(row.get("数据集编号", "")).casefold()]
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
            return None, f"分析数据集 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于数据集管理可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"分析数据集已{action}"

    # ------------------------------------------------------ 字段分区摘要
    def _require_entry(self, entry_id: int) -> dict[str, Any]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            raise ValueError(f"分析数据集 {entry_id} 不存在或已归档")
        return entry

    def get_field_summary(self, entry_id: int, *, changed_only: bool = False) -> dict[str, Any]:
        """字段契约读取：按当前版本返回分区字段摘要视图。"""
        self._require_entry(entry_id)
        view = field_summary_service.get_view(entry_id, changed_only=changed_only)
        if view is None:
            raise ValueError(f"分析数据集 {entry_id} 尚未生成字段分区摘要")
        return view

    def refresh_field_summary(self, entry_id: int) -> dict[str, Any]:
        """本轮加工：读取当前分区字段清单，只重建变化分区并原子提交新版本。"""
        self._require_entry(entry_id)
        return field_summary_service.refresh(entry_id)

    def list_summary_versions(self, entry_id: int) -> list[dict[str, Any]]:
        """回查字段分区摘要的保留版本。"""
        self._require_entry(entry_id)
        return field_summary_service.list_versions(entry_id)

    def get_summary_version(self, entry_id: int, version: int) -> dict[str, Any]:
        self._require_entry(entry_id)
        snapshot = field_summary_service.get_version(entry_id, version)
        if snapshot is None:
            raise ValueError(f"版本 {version} 不存在，无法回查")
        return snapshot

    def reconcile_partition(
        self, entry_id: int, partition_id: str, result: str, *, remark: str | None = None
    ) -> dict[str, Any]:
        """写入字段分区摘要核对结果；同一分区同版本只保留一份有效核对结果。"""
        self._require_entry(entry_id)
        if result not in RECONCILE_RESULTS:
            raise ValueError(f"核对结果「{result}」不在允许范围：{'、'.join(sorted(RECONCILE_RESULTS))}")
        return field_summary_service.reconcile(entry_id, partition_id, result, remark=remark)

    def simulate_partition_drift(
        self, entry_id: int, partition_id: str, fields: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """演示/联调用：让外部数据源的某个分区发生字段变化，等待下一轮刷新读取。"""
        self._require_entry(entry_id)
        if not fields:
            raise ValueError("分区字段清单不能为空，否则无法模拟变化")
        normalized: list[dict[str, Any]] = []
        for item in fields:
            name = str(item.get("字段名称", "")).strip()
            if not name:
                raise ValueError("每个字段都必须提供字段名称")
            normalized.append({
                "分区编号": partition_id,
                "分区类型": item.get("分区类型", "daily"),
                "分区完成时间": item.get("分区完成时间", ""),
                "字段名称": name,
                "字段类型": str(item.get("字段类型", "")).strip(),
            })
        field_summary_service.simulate_drift(entry_id, partition_id, normalized)
        return {"ok": True, "分区编号": partition_id, "字段数": len(normalized)}

