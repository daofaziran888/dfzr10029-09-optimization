"""字段分区摘要服务：替代整批重建字段元数据的刷新方式。

设计要点（对应本轮验收口径）：

1. 分区化：每个数据集维护若干分区（日分区 + 全量字段清单分区），刷新时按
   分区读取当前字段清单并计算内容签名，只有签名变化的分区才重建摘要。
2. 字段顺序稳定：全局字段注册表记录字段首次出现的位置，刷新中遇到新字段只
   追加到队尾，已存在的字段永远保留原位置，页面与查询模板看到的顺序一致。
3. 同一轮确定：分区摘要与字段顺序在同一次 refresh 调用内构建并原子提交
   （先在临时视图上加工，再一次性替换可见视图），页面不会先看到新分区再回
   到旧字段位置。
4. 单一有效版本：每次提交生成一个自增版本，旧版本保留可回查，但 current_version
   只指向最新一份；核对冲突（并发/重复核对）时也只落一份唯一核对结果。
5. 共享来源：数据集页面、查询模板、运营概览都通过本服务读取摘要，跨模块
   复用同一份来源记录，不各自拼装。
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime
from typing import Any

# 分区类型
PARTITION_DAILY = "daily"
PARTITION_FULL = "full"

# 核对状态
RECONCILE_PENDING = "待核对"
RECONCILE_CONFIRMED = "核对通过"
RECONCILE_REJECTED = "核对驳回"
RECONCILE_CONFLICT = "冲突待裁决"
# 外部允许写入的核对结论（待核对只能由刷新流程产生，不接受直接写入）
RECONCILE_RESULTS = {RECONCILE_CONFIRMED, RECONCILE_REJECTED, RECONCILE_CONFLICT}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _signature(fields: list[dict[str, Any]]) -> str:
    """字段清单内容签名：字段名、类型、分区归属都一致才视为未变化。"""
    payload = [
        {
            "name": item.get("字段名称"),
            "type": item.get("字段类型"),
            "partition": item.get("分区编号"),
        }
        for item in fields
    ]
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class FieldSummaryService:
    """进程内字段分区摘要仓库；真实项目里这一层会换成数据库事务。"""

    def __init__(self) -> None:
        # dataset_id -> 字段分区摘要视图（可变状态，只在刷新原子提交时整体替换）
        self._views: dict[int, dict[str, Any]] = {}
        # dataset_id -> 全局字段注册表：[{字段名称, 字段类型, 首次出现版本}]
        self._field_registry: dict[int, list[dict[str, Any]]] = {}
        # dataset_id -> 历史版本归档，保留版本用于回查
        self._versions: dict[int, list[dict[str, Any]]] = {}
        # 模拟外部数据源的当前分区字段清单（"读取当前数据"的来源）
        self._sources: dict[int, list[dict[str, Any]]] = {}
        # 数据集编号 -> dataset_id 的反查表，供跨模块按编号取数
        self._code_index: dict[str, int] = {}

    # ------------------------------------------------------------------ 数据源
    def register_dataset(self, entry_id: int, dataset_code: str) -> None:
        """登记数据集与编号的映射，供查询模板等跨模块按编号定位摘要。"""
        self._code_index[dataset_code] = entry_id
        self._views.setdefault(entry_id, self._empty_view(entry_id))
        self._field_registry.setdefault(entry_id, [])
        self._versions.setdefault(entry_id, [])
        self._sources.setdefault(entry_id, [])

    def seed_partitions(self, entry_id: int, partitions: list[dict[str, Any]]) -> None:
        """写入示例分区字段清单，模拟从数仓读到的当前数据。"""
        self._sources[entry_id] = copy.deepcopy(partitions)

    def read_partition_fields(self, entry_id: int, partition_id: str) -> list[dict[str, Any]]:
        """读取当前数据：按既有取数调用关系读取单个分区的字段清单。"""
        return [
            copy.deepcopy(item)
            for item in self._sources.get(entry_id, [])
            if item.get("分区编号") == partition_id
        ]

    def read_current_partitions(self, entry_id: int) -> list[dict[str, Any]]:
        """读取当前数据：按分区聚合外部数据源当前的字段清单。"""
        grouped: dict[str, list[dict[str, Any]]] = {}
        order: list[str] = []
        for item in self._sources.get(entry_id, []):
            pid = str(item.get("分区编号"))
            if pid not in grouped:
                grouped[pid] = []
                order.append(pid)
            grouped[pid].append(copy.deepcopy(item))
        return [
            {
                "分区编号": pid,
                "分区类型": grouped[pid][0].get("分区类型", PARTITION_DAILY),
                "分区完成时间": grouped[pid][0].get("分区完成时间", ""),
                "fields": grouped[pid],
            }
            for pid in order
        ]

    def simulate_drift(self, entry_id: int, partition_id: str, fields: list[dict[str, Any]]) -> None:
        """测试/演示钩子：让外部数据源的某个分区产生字段变化，下一轮刷新才能读到。"""
        source = self._sources.setdefault(entry_id, [])
        source[:] = [item for item in source if item.get("分区编号") != partition_id]
        source.extend(copy.deepcopy(fields))

    # ------------------------------------------------------------------ 刷新
    def refresh(self, entry_id: int, *, changed_only: bool = True) -> dict[str, Any]:
        """本轮加工：读取当前数据 → 汇总变化分区 → 重建字段摘要 → 原子提交。

        返回的视图里 changed_partitions 只列出本轮真正发生变化的分区，
        未变化分区沿用上一版摘要，字段顺序沿用上一版注册表位置。
        """
        current = self._views.get(entry_id)
        if current is None:
            current = self._empty_view(entry_id)
            self._views[entry_id] = current

        # 1. 在临时视图上加工，刷新中途页面读到的仍是上一版（原子性）。
        working = copy.deepcopy(current)
        registry = copy.deepcopy(self._field_registry.get(entry_id, []))

        incoming = self.read_current_partitions(entry_id)
        incoming_ids = {part["分区编号"] for part in incoming}
        old_summaries = {item["分区编号"]: item for item in working["partition_summaries"]}

        new_summaries: list[dict[str, Any]] = []
        changed_partitions: list[dict[str, Any]] = []
        next_seq = working.get("latest_change_seq", 0)

        for part in incoming:
            signature = _signature(part["fields"])
            previous = old_summaries.get(part["分区编号"])
            # 2. 只刷新变化分区：签名相同且已有摘要时整体沿用，不参与重建。
            #    但刚从"已下线"恢复的分区属于生命周期变化，即使内容签名相同
            #    也要重新标记并计入本轮变化分区。
            if (
                previous
                and previous.get("signature") == signature
                and previous.get("分区状态") != "已下线"
                and changed_only
            ):
                new_summaries.append(copy.deepcopy(previous))
                continue

            added: list[str] = []
            removed: list[str] = []
            type_changed: list[dict[str, str]] = []
            incoming_names: list[str] = []
            for field in part["fields"]:
                name = str(field.get("字段名称"))
                incoming_names.append(name)
                matched = next((item for item in registry if item["字段名称"] == name), None)
                if matched is None:
                    # 3. 新字段只追加到队尾，老字段位置不动 → 顺序稳定。
                    registry.append({
                        "字段名称": name,
                        "字段类型": field.get("字段类型", ""),
                        "首次出现版本": working.get("current_version", 0) + 1,
                    })
                    added.append(name)
                elif matched.get("字段类型") != field.get("字段类型", ""):
                    type_changed.append({
                        "字段名称": name,
                        "原类型": str(matched.get("字段类型", "")),
                        "新类型": str(field.get("字段类型", "")),
                    })
            if previous:
                previous_names = {name for name in previous.get("field_order", [])}
                removed = [name for name in previous_names if name not in incoming_names]

            next_seq += 1
            lifecycle = "重新上线" if previous and previous.get("分区状态") == "已下线" else (
                "新建" if previous is None else "字段变化")
            summary = {
                "分区编号": part["分区编号"],
                "分区类型": part["分区类型"],
                "分区完成时间": part["分区完成时间"],
                "field_order": incoming_names,
                "field_details": [
                    {"字段名称": str(field.get("字段名称")), "字段类型": str(field.get("字段类型", ""))}
                    for field in part["fields"]
                ],
                "field_count": len(incoming_names),
                "signature": signature,
                "last_change_seq": next_seq,
                "last_refreshed_at": _now(),
                "changes": {
                    "lifecycle": lifecycle,
                    "added": added,
                    "removed": removed,
                    "type_changed": type_changed,
                },
            }
            new_summaries.append(summary)
            changed_partitions.append(copy.deepcopy(summary))

        # 数据源里已经不存在的分区标记下线，同样计入变化；已下线的分区只保留
        # 在视图里，不重复计入后续刷新的变化分区。
        for pid, previous in old_summaries.items():
            if pid not in incoming_ids:
                if previous.get("分区状态") == "已下线":
                    new_summaries.append(copy.deepcopy(previous))
                    continue
                retired = copy.deepcopy(previous)
                retired["分区状态"] = "已下线"
                next_seq += 1
                retired["last_change_seq"] = next_seq
                changed_partitions.append(retired)
                new_summaries.append(retired)

        # 4. 同一轮确定：分区摘要顺序按分区完成时间之外的稳定规则——沿用既有
        #    分区出现顺序，新增分区追加到队尾，避免刷新间顺序跳动。
        stable_order = [item["分区编号"] for item in working["partition_summaries"]]
        for part in new_summaries:
            if part["分区编号"] not in stable_order:
                stable_order.append(part["分区编号"])
        new_summaries.sort(key=lambda item: stable_order.index(item["分区编号"]))

        new_version = int(working.get("current_version", 0)) + 1
        working.update({
            "dataset_id": entry_id,
            "current_version": new_version,
            "partition_summaries": new_summaries,
            "changed_partitions": changed_partitions,
            "field_order": [item["字段名称"] for item in registry],
            "field_registry": registry,
            "latest_change_seq": next_seq,
            "refreshed_at": _now(),
        })
        # 待核对项：本轮每个变化分区产生一条，概览按当前版本汇总待核对量。
        # 待核对项与版本同轮确定；未核对的变化不会丢失——对应版本已整体归档，
        # 且分区摘要的 changes 会一直保留到该分区下次变化。
        working["pending_reconciles"] = [
            {
                "核对编号": f"REC-{entry_id}-{new_version}-{idx + 1:02d}",
                "分区编号": item["分区编号"],
                "版本": new_version,
                "核对状态": RECONCILE_PENDING,
                "变化摘要": item["changes"],
            }
            for idx, item in enumerate(changed_partitions)
        ]

        # 5. 原子提交：临时视图加工完成后一次性替换可见状态与注册表。
        self._views[entry_id] = working
        self._field_registry[entry_id] = registry
        self._versions[entry_id].append(copy.deepcopy(working))
        return copy.deepcopy(working)

    # ------------------------------------------------------------------ 查询
    def get_view(self, entry_id: int, *, changed_only: bool = False) -> dict[str, Any] | None:
        """字段契约接口：页面视图按当前版本排列；changed_only 时只返回变化分区。"""
        view = self._views.get(entry_id)
        if view is None:
            return None
        payload = copy.deepcopy(view)
        if changed_only:
            payload["partition_summaries"] = copy.deepcopy(view.get("changed_partitions", []))
        return payload

    def get_version(self, entry_id: int, version: int) -> dict[str, Any] | None:
        """回查字段分区摘要的历史版本。"""
        for snapshot in self._versions.get(entry_id, []):
            if int(snapshot.get("current_version", 0)) == version:
                return copy.deepcopy(snapshot)
        return None

    def list_versions(self, entry_id: int) -> list[dict[str, Any]]:
        return [
            {"版本": item["current_version"], "refreshed_at": item.get("refreshed_at"),
             "变化分区数": len(item.get("changed_partitions", []))}
            for item in self._versions.get(entry_id, [])
        ]

    def resolve_id_by_code(self, dataset_code: str) -> int | None:
        return self._code_index.get(dataset_code)

    # ------------------------------------------------------------------ 核对
    def reconcile(
        self,
        entry_id: int,
        partition_id: str,
        result: str,
        *,
        remark: str | None = None,
    ) -> dict[str, Any]:
        """写入字段分区摘要核对结果并保留对应版本。

        同一分区同一版本重复/冲突提交时，只保留一份有效核对结果（后一次以
        冲突裁决方式覆盖待核对记录），保证唯一核对结果。
        """
        view = self._views.get(entry_id)
        if view is None:
            raise ValueError(f"数据集 {entry_id} 尚未生成字段分区摘要")
        if result not in RECONCILE_RESULTS:
            raise ValueError(
                f"核对结果「{result}」不在允许范围：{'、'.join(sorted(RECONCILE_RESULTS))}")
        version = int(view.get("current_version", 0))
        pending = view.setdefault("pending_reconciles", [])
        existing = next(
            (item for item in pending if item["分区编号"] == partition_id and item["版本"] == version),
            None,
        )
        record = {
            "核对编号": existing["核对编号"] if existing else f"REC-{entry_id}-{version}-{partition_id}",
            "分区编号": partition_id,
            "版本": version,
            "核对状态": result,
            "变化摘要": existing.get("变化摘要", {}) if existing else {},
            "核对说明": remark or "",
            "核对时间": _now(),
        }
        if existing:
            # 冲突后仍需唯一核对结果：原地更新，不新增第二条。
            existing.update(record)
            target = existing
        else:
            pending.append(record)
            target = record
        # 已落定核对结果的条目移出待核对队列，概览待核对量随之下降。
        view["pending_reconciles"] = [
            item for item in pending if item.get("核对状态") == RECONCILE_PENDING
        ]
        history = view.setdefault("reconcile_history", [])
        history = [item for item in history if not (
            item["分区编号"] == partition_id and item["版本"] == version)]
        history.append(copy.deepcopy(target))
        view["reconcile_history"] = history
        return copy.deepcopy(target)

    def overview(self) -> dict[str, int]:
        """概览：跨数据集汇总字段分区摘要的待核对项。"""
        datasets = 0
        pending = 0
        partitions = 0
        changed = 0
        for view in self._views.values():
            datasets += 1
            pending += len(view.get("pending_reconciles", []))
            partitions += len(view.get("partition_summaries", []))
            changed += len(view.get("changed_partitions", []))
        return {
            "摘要数据集": datasets,
            "分区总数": partitions,
            "本轮变化分区": changed,
            "待核对项": pending,
        }

    def _empty_view(self, entry_id: int) -> dict[str, Any]:
        return {
            "dataset_id": entry_id,
            "current_version": 0,
            "partition_summaries": [],
            "changed_partitions": [],
            "field_order": [],
            "field_registry": [],
            "pending_reconciles": [],
            "reconcile_history": [],
            "latest_change_seq": 0,
            "refreshed_at": None,
        }


# 进程级单例：所有模块共享同一份字段分区摘要来源记录。
field_summary_service = FieldSummaryService()
