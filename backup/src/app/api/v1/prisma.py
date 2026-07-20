from typing import Any
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import Response

from app.api.deps import ActorId, DbSession
from app.schemas.prisma import PrismaFlowUpdate
from app.services.prisma import PrismaService

router = APIRouter()


@router.get("/{project_id}/prisma", response_model=dict[str, Any])
def get_prisma(project_id: UUID, db: DbSession):
    return PrismaService(db).get_flow(project_id)


@router.put("/{project_id}/prisma", response_model=dict[str, Any])
def update_prisma(project_id: UUID, payload: PrismaFlowUpdate, db: DbSession, actor_id: ActorId):
    data = payload.model_dump()
    notes = data.pop("notes", None)
    return PrismaService(db).upsert_flow(project_id, data, notes, actor_id)


@router.get("/{project_id}/prisma/diagram")
def get_prisma_diagram(project_id: UUID, db: DbSession):
    flow = PrismaService(db).get_flow(project_id)
    png = PrismaService.render_diagram(flow["data"])
    return Response(content=png, media_type="image/png")
