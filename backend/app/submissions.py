"""Explicit user submissions; no automatic approval or reputation changes."""
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from app.models import Appeal, Channel, Install, Report
from app.schemas import Submission
from app.rate_limit import enforce_submission_limits

router = APIRouter(prefix="/v1", tags=["submissions"])


class SubmissionResult(BaseModel):
    id: UUID
    created: bool


def result(identifier: UUID, created: bool) -> JSONResponse:
    return JSONResponse(
        {"id": str(identifier), "created": created}, status_code=201 if created else 200,
        headers={"Cache-Control": "no-store"},
    )


def unavailable() -> HTTPException:
    return HTTPException(503, "Submission temporarily unavailable; please retry.",
                         headers={"Retry-After": "5", "Cache-Control": "no-store"})


@router.post("/reports", response_model=SubmissionResult, status_code=201, dependencies=[Depends(enforce_submission_limits)], responses={200: {}, 429: {}, 503: {}})
def report(payload: Submission, request: Request) -> JSONResponse:
    try:
        with request.app.state.engine.begin() as connection:
            connection.exec_driver_sql("SET LOCAL lock_timeout = '3s'")
            connection.exec_driver_sql("SET LOCAL statement_timeout = '10s'")
            # Never overwrite moderation, score, handle, or reputation on conflict.
            channel_id = connection.scalar(insert(Channel).values(
                youtube_channel_id=payload.channel_id,
            ).on_conflict_do_nothing(index_elements=["youtube_channel_id"]).returning(Channel.id))
            if channel_id is None:
                channel_id = connection.scalar(select(Channel.id).where(Channel.youtube_channel_id == payload.channel_id))
            # Serialize scoring and moderation for this channel before inserting a report.
            channel = connection.execute(select(Channel.id, Channel.status).where(
                Channel.id == channel_id,
            ).with_for_update()).one()
            connection.execute(insert(Install).values(id=payload.install_id).on_conflict_do_nothing(index_elements=["id"]))
            identifier = connection.scalar(insert(Report).values(
                channel_id=channel_id, install_id=payload.install_id, reason=payload.reason,
            ).on_conflict_do_nothing(constraint="uq_reports_install_channel").returning(Report.id))
            created = identifier is not None
            if created:
                score = connection.scalar(select(func.coalesce(func.sum(Install.reputation), 0)).select_from(
                    Report.__table__.join(Install, Report.install_id == Install.id)
                ).where(Report.channel_id == channel_id))
                # Saturate at the schema's maximum rather than rejecting valid reports.
                score = min(score, Decimal("99999999.9999"))
                status = channel.status
                if status == "unreviewed" and score >= request.app.state.settings.review_threshold:
                    status = "pending_review"
                connection.execute(update(Channel).where(Channel.id == channel_id).values(score=score, status=status))
            if identifier is None:
                identifier = connection.scalar(select(Report.id).where(
                    Report.channel_id == channel_id, Report.install_id == payload.install_id,
                ))
            if identifier is None:
                raise unavailable()
        return result(identifier, created)
    except SQLAlchemyError:
        raise unavailable() from None


@router.post("/appeals", response_model=SubmissionResult, status_code=201, dependencies=[Depends(enforce_submission_limits)], responses={200: {}, 404: {}, 409: {}, 429: {}, 503: {}})
def appeal(payload: Submission, request: Request) -> JSONResponse:
    try:
        with request.app.state.engine.begin() as connection:
            connection.exec_driver_sql("SET LOCAL lock_timeout = '3s'")
            connection.exec_driver_sql("SET LOCAL statement_timeout = '10s'")
            channel = connection.execute(select(Channel.id, Channel.status).where(
                Channel.youtube_channel_id == payload.channel_id,
            ).with_for_update()).first()
            if channel is None:
                raise HTTPException(404, "Channel is not in the blocklist.")
            if channel.status != "approved":
                raise HTTPException(409, "Channel is no longer approved for blocking.")
            connection.execute(insert(Install).values(id=payload.install_id).on_conflict_do_nothing(index_elements=["id"]))
            identifier = connection.scalar(insert(Appeal).values(
                channel_id=channel.id, install_id=payload.install_id, reason=payload.reason,
            ).on_conflict_do_nothing(
                index_elements=["install_id", "channel_id"],
                index_where=text("status = 'open' AND install_id IS NOT NULL"),
            ).returning(Appeal.id))
            created = identifier is not None
            if identifier is None:
                identifier = connection.scalar(select(Appeal.id).where(
                    Appeal.channel_id == channel.id, Appeal.install_id == payload.install_id, Appeal.status == "open",
                ))
            if identifier is None:
                raise unavailable()
        return result(identifier, created)
    except SQLAlchemyError:
        raise unavailable() from None
