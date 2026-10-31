"""Manual decisions are the only route from community reports to blocking."""
from contextlib import contextmanager
from secrets import compare_digest
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.models import Appeal, Channel, Install, ModerationAction, Report

key_header = APIKeyHeader(name="X-Admin-Key", auto_error=False)
NO_STORE = {"Cache-Control": "no-store"}


def authenticate(request: Request, response: Response, key: str | None = Depends(key_header)) -> None:
    response.headers.update(NO_STORE)
    configured = request.app.state.settings.admin_api_key.get_secret_value()
    if not configured:
        raise HTTPException(503, "Admin API is disabled.", headers=NO_STORE)
    if key is None or not compare_digest(key.encode(), configured.encode()):
        raise HTTPException(401, "Invalid admin API key.", headers=NO_STORE)


router = APIRouter(prefix="/v1/admin", tags=["moderation"], dependencies=[Depends(authenticate)])


class ChannelDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Literal["approve", "reject"]
    reason: str = Field(min_length=1, max_length=2000)


class AppealDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Literal["accept", "reject"]
    reason: str = Field(min_length=1, max_length=2000)


@contextmanager
def transaction(request: Request):
    try:
        with request.app.state.engine.begin() as connection:
            connection.exec_driver_sql("SET LOCAL lock_timeout = '3s'")
            connection.exec_driver_sql("SET LOCAL statement_timeout = '10s'")
            yield connection
    except SQLAlchemyError:
        raise HTTPException(503, "Moderation temporarily unavailable; please retry.",
                            headers={**NO_STORE, "Retry-After": "5"}) from None


@router.get("/channels")
def channels(request: Request, status: Literal["unreviewed", "pending_review", "approved", "rejected"] = "pending_review",
             limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    with transaction(request) as connection:
        rows = connection.execute(select(Channel.id, Channel.youtube_channel_id, Channel.handle,
                                         Channel.status, Channel.score, Channel.updated_at).where(
            Channel.status == status).order_by(Channel.created_at, Channel.id).limit(limit).offset(offset))
        return {"channels": [dict(row._mapping) for row in rows]}


@router.get("/channels/{channel_id}/reports")
def reports(channel_id: UUID, request: Request, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    with transaction(request) as connection:
        if connection.scalar(select(Channel.id).where(Channel.id == channel_id)) is None:
            raise HTTPException(404, "Channel not found.", headers=NO_STORE)
        rows = connection.execute(select(Report.id, Report.reason, Report.created_at, Install.reputation).join(
            Install, Report.install_id == Install.id).where(Report.channel_id == channel_id).order_by(
            Report.created_at, Report.id).limit(limit).offset(offset))
        return {"reports": [dict(row._mapping) for row in rows]}


@router.get("/appeals")
def appeals(request: Request, status: Literal["open", "accepted", "rejected"] = "open",
            limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    with transaction(request) as connection:
        rows = connection.execute(select(Appeal.id, Appeal.channel_id, Channel.youtube_channel_id,
                                         Appeal.reason, Appeal.status, Appeal.created_at, Appeal.resolved_at).join(
            Channel, Appeal.channel_id == Channel.id).where(Appeal.status == status).order_by(
            Appeal.created_at, Appeal.id).limit(limit).offset(offset))
        return {"appeals": [dict(row._mapping) for row in rows]}


@router.post("/channels/{channel_id}/decision")
def decide_channel(channel_id: UUID, payload: ChannelDecision, request: Request):
    with transaction(request) as connection:
        channel = connection.execute(select(Channel.id, Channel.status).where(
            Channel.id == channel_id).with_for_update()).first()
        if channel is None:
            raise HTTPException(404, "Channel not found.", headers=NO_STORE)
        status = "approved" if payload.action == "approve" else "rejected"
        if channel.status == status:
            return {"channel_id": channel_id, "status": status, "changed": False}
        connection.execute(update(Channel).where(Channel.id == channel_id).values(status=status))
        connection.execute(ModerationAction.__table__.insert().values(
            channel_id=channel_id, action=payload.action, actor="admin-api", reason=payload.reason))
        return {"channel_id": channel_id, "status": status, "changed": True}


@router.post("/appeals/{appeal_id}/decision")
def decide_appeal(appeal_id: UUID, payload: AppealDecision, request: Request):
    with transaction(request) as connection:
        channel_id = connection.scalar(select(Appeal.channel_id).where(Appeal.id == appeal_id))
        if channel_id is None:
            raise HTTPException(404, "Appeal not found.", headers=NO_STORE)
        # Same channel-first lock order as report, appeal creation and channel decisions.
        connection.execute(select(Channel.id).where(Channel.id == channel_id).with_for_update()).one()
        status = connection.scalar(select(Appeal.status).where(Appeal.id == appeal_id).with_for_update())
        resolved = "accepted" if payload.action == "accept" else "rejected"
        if status != "open":
            if status == resolved:
                return {"appeal_id": appeal_id, "status": status, "changed": False}
            raise HTTPException(409, "Appeal already resolved with a different decision.", headers=NO_STORE)
        connection.execute(update(Appeal).where(Appeal.id == appeal_id).values(status=resolved, resolved_at=func.now()))
        if payload.action == "accept":
            connection.execute(update(Channel).where(Channel.id == channel_id).values(status="rejected"))
        connection.execute(ModerationAction.__table__.insert().values(
            channel_id=channel_id, appeal_id=appeal_id, action=f"{payload.action}_appeal",
            actor="admin-api", reason=payload.reason))
        return {"appeal_id": appeal_id, "status": resolved, "changed": True}
