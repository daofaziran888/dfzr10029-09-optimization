"""数据集管理接口：维护分析数据集，覆盖完成接入、启用数据集、归档数据集等动作。"""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.schemas import ActionPayload, ActionResult, EntryPayload, PageResult
from app.services.dataset import DatasetService

router = APIRouter(prefix="/api/dataset", tags=["数据集管理"])

service = DatasetService()

LIST_FIELDS = ["数据集编号", "数据集名称", "来源类型", "字段数量", "行数估算", "刷新周期", "负责人", "数据集状态"]
STATUSES = ["待接入", "已接入", "使用中", "已归档"]


class ReconcilePayload(BaseModel):
    """字段分区摘要核对契约。"""

    partition_id: str
    result: str
    remark: str | None = None


class DriftPayload(BaseModel):
    """模拟分区字段清单变化的联调契约。"""

    fields: list[dict[str, object]]


def query_filters(request: Request) -> dict[str, str]:
    """只接受当前模块声明过的字段，忽略分页等保留参数。"""
    return {
        key: value.strip()
        for key, value in request.query_params.items()
        if key in LIST_FIELDS and value.strip()
    }


@router.get("", response_model=PageResult[dict])
def list_entries(
    request: Request,
    keyword: str | None = Query(default=None, description="按数据集编号检索"),
    status: str | None = Query(default=None, description="待接入、已接入、使用中、已归档"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResult[dict]:
    """按页面字段、数据集编号关键字与状态过滤数据集管理列表。"""
    items, total = service.list_entries(
        filters=query_filters(request), keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries(
    request: Request,
    keyword: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> StreamingResponse:
    """下载当前筛选条件下的 UTF-8 CSV；必须声明在 /{entry_id} 之前。"""
    items, _ = service.list_entries(
        filters=query_filters(request), keyword=keyword, status=status, page=1, size=1000000)
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["id", *LIST_FIELDS, "status"])
    for item in items:
        row = []
        for value in [item.get("id"), *(item.get(field, "") for field in LIST_FIELDS), item.get("status", "")]:
            text = "" if value is None else str(value)
            row.append("'" + text if text.startswith(("=", "+", "-", "@")) else text)
        writer.writerow(row)
    return StreamingResponse(
        iter([output.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="dataset.csv"'})


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条分析数据集明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"分析数据集 {entry_id} 不存在或已归档")
    return entry


@router.get("/{entry_id}/field-summary", response_model=dict)
def get_field_summary(
    entry_id: int,
    changed_only: bool = Query(default=False, description="为 true 时只返回本轮发生变化的分区"),
) -> dict:
    """字段契约接口：读取字段分区摘要视图，按当前版本排列。"""
    try:
        return service.get_field_summary(entry_id, changed_only=changed_only)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{entry_id}/field-summary/refresh", response_model=ActionResult)
def refresh_field_summary(entry_id: int) -> ActionResult:
    """读取当前分区字段清单，汇总变化分区并重建字段摘要，原子提交一个新版本。"""
    try:
        view = service.refresh_field_summary(entry_id)
    except ValueError as exc:
        return ActionResult(ok=False, message=str(exc))
    changed = len(view.get("changed_partitions", []))
    return ActionResult(
        ok=True,
        message=f"字段分区摘要已刷新到版本 {view['current_version']}，本轮变化分区 {changed} 个",
        entry=view,
    )


@router.get("/{entry_id}/field-summary/versions", response_model=dict)
def list_summary_versions(entry_id: int) -> dict:
    """回查字段分区摘要保留的版本清单。"""
    try:
        versions = service.list_summary_versions(entry_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"items": versions, "total": len(versions)}


@router.get("/{entry_id}/field-summary/versions/{version}", response_model=dict)
def get_summary_version(entry_id: int, version: int) -> dict:
    """按版本号回查某一版字段分区摘要。"""
    try:
        return service.get_summary_version(entry_id, version)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{entry_id}/field-summary/reconcile", response_model=ActionResult)
def reconcile_partition(entry_id: int, payload: ReconcilePayload) -> ActionResult:
    """写入字段分区摘要核对结果并保留对应版本；冲突时仍只保留一份有效结果。"""
    try:
        record = service.reconcile_partition(
            entry_id, payload.partition_id.strip(), payload.result.strip(), remark=payload.remark)
    except ValueError as exc:
        return ActionResult(ok=False, message=str(exc))
    return ActionResult(ok=True, message=f"分区 {record['分区编号']} 核对结果已写入", entry=record)


@router.post("/{entry_id}/field-summary/simulate-drift", response_model=ActionResult)
def simulate_drift(entry_id: int, payload: DriftPayload) -> ActionResult:
    """联调钩子：模拟外部数据源分区字段变化，下一轮刷新才会体现在摘要里。"""
    partition_id = str(payload.fields[0].get("分区编号", "")) if payload.fields else ""
    try:
        result = service.simulate_partition_drift(entry_id, partition_id, payload.fields)
    except (ValueError, IndexError, KeyError) as exc:
        return ActionResult(ok=False, message=f"模拟变化失败：{exc}")
    return ActionResult(ok=True, message="数据源分区字段已变化，等待下一轮刷新", entry=result)


@router.post("", response_model=ActionResult)
def create_entry(payload: dict[str, object]) -> ActionResult:
    """登记一条分析数据集，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="分析数据集已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: ActionPayload) -> ActionResult:
    """对单条分析数据集执行完成接入、启用数据集、归档数据集；不允许的动作会被拦下并说明原因。"""
    entry, message = service.run_action(entry_id, payload.action.strip())
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
