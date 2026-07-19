from fastapi import APIRouter, Depends

from app.api.deps import require_project_member
from app.api.v1 import (
    auth,
    datasets,
    documents,
    extractions,
    health,
    jobs,
    ml,
    organizations,
    projects,
    reports,
    search,
    system,
    terms,
)

api_router = APIRouter()
api_router.include_router(auth.router, tags=["认证"])
api_router.include_router(health.router, tags=["健康检查"])
api_router.include_router(organizations.router, prefix="/organizations", tags=["组织"])
api_router.include_router(projects.router, prefix="/projects", tags=["项目"])
project_dependencies = [Depends(require_project_member)]
api_router.include_router(
    documents.router, prefix="/projects", tags=["文献"], dependencies=project_dependencies
)
api_router.include_router(
    jobs.router, prefix="/projects", tags=["任务"], dependencies=project_dependencies
)
api_router.include_router(
    search.router, prefix="/projects", tags=["检索"], dependencies=project_dependencies
)
api_router.include_router(
    terms.router, prefix="/projects", tags=["词元与字段"], dependencies=project_dependencies
)
api_router.include_router(
    extractions.router, prefix="/projects", tags=["数据抽取"], dependencies=project_dependencies
)
api_router.include_router(
    datasets.router, prefix="/projects", tags=["数据集"], dependencies=project_dependencies
)
api_router.include_router(
    ml.router, prefix="/projects", tags=["机器学习与优化"], dependencies=project_dependencies
)
api_router.include_router(
    reports.router, prefix="/projects", tags=["报告"], dependencies=project_dependencies
)
api_router.include_router(system.router, tags=["系统配置与审计"])
