"""数据分析实验与数据应用服务平台 后端服务入口。

启动：uvicorn app.main:app --host 127.0.0.1 --port 8000
健康检查：GET /api/health
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import ROUTERS
from app.services.field_summary import field_summary_service
from app.services.field_summary_seed import bootstrap_field_summaries
from app.store import store

app = FastAPI(title="数据分析实验与数据应用服务平台", version="1.0.0")


@app.on_event("startup")
def load_field_summaries() -> None:
    """启动时读取分区字段清单并生成首轮字段分区摘要（只在内存仓库里执行一次）。"""
    bootstrap_field_summaries()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in ROUTERS:
    app.include_router(module.router)


@app.get("/api/health")
def health() -> dict[str, object]:
    """健康检查：确认服务已经监听、示例数据已经就绪。"""
    return {"ok": True, "app": settings.app_name, "modules": len(store.module_names())}


@app.get("/api/overview")
def overview() -> dict[str, object]:
    """运营概览：把各业务模块的待处理量汇总成看板卡片。"""
    payload = store.overview()
    # 字段分区摘要概览：待核对项按当前版本统计，与数据集页面共用同一来源。
    payload["field_summary"] = field_summary_service.overview()
    return payload
