"""Local-cache synchronization. Requests contain no browsing identifiers."""
from datetime import UTC, datetime
from hashlib import sha256
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.models import Channel

router = APIRouter(prefix="/v1", tags=["blocklist"])
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class BlocklistChannel(BaseModel):
    youtube_channel_id: str
    handle: str | None
    updated_at: datetime


class BlocklistDelta(BaseModel):
    full_sync: bool
    channels: list[BlocklistChannel]
    removed_channel_ids: list[str]
    next_since: datetime


def etag_matches(header: str | None, etag: str) -> bool:
    # GET uses weak comparison: W/"tag" and "tag" match the same representation.
    return header is not None and any(
        candidate.strip().removeprefix("W/") in ("*", etag)
        for candidate in header.split(",")
    )


@router.get("/blocklist", response_model=BlocklistDelta, responses={304: {}, 503: {}})
def get_blocklist(
    request: Request,
    since: Annotated[AwareDatetime | None, Query(description="Use the previous next_since verbatim; omit for a full snapshot.")] = None,
    if_none_match: Annotated[str | None, Header()] = None,
) -> Response:
    since = since.astimezone(UTC) if since is not None else None
    try:
        with request.app.state.engine.begin() as connection:
            connection.exec_driver_sql("SET LOCAL lock_timeout = '3s'")
            connection.exec_driver_sql("SET LOCAL statement_timeout = '10s'")
            # Wait for in-flight writes, then block new writes until this read ends.
            # READ COMMITTED gives the subsequent SELECT a fresh committed view.
            connection.exec_driver_sql("LOCK TABLE channels IN SHARE MODE")
            now = connection.scalar(select(func.clock_timestamp()))
            if since is not None and (since < EPOCH or since > now):
                raise HTTPException(422, "since must be between the Unix epoch and current server time")
            latest = connection.scalar(select(func.max(Channel.updated_at)))
            cursor = max(latest or EPOCH, since or EPOCH).astimezone(UTC)
            query = select(Channel.youtube_channel_id, Channel.handle, Channel.status, Channel.updated_at)
            if since is None:
                query = query.where(Channel.status == "approved")
            else:
                # Inclusive boundary makes equal timestamps safe; applying a delta
                # must be idempotent. The timestamp must retain microsecond precision.
                query = query.where(Channel.updated_at >= since)
            rows = connection.execute(query.order_by(Channel.updated_at, Channel.id)).all()
    except SQLAlchemyError:
        # Do not expose connection URLs, SQL parameters, or database exceptions.
        raise HTTPException(503, "Blocklist temporarily unavailable", headers={"Retry-After": "5"}) from None

    delta = BlocklistDelta(
        full_sync=since is None,
        channels=[BlocklistChannel(
            youtube_channel_id=row.youtube_channel_id,
            handle=row.handle,
            updated_at=row.updated_at.astimezone(UTC),
        ) for row in rows if row.status == "approved"],
        removed_channel_ids=[row.youtube_channel_id for row in rows if row.status != "approved"],
        next_since=cursor,
    )
    response = JSONResponse(delta.model_dump(mode="json"))
    etag = '"' + sha256(response.body).hexdigest() + '"'
    headers = {"ETag": etag, "Cache-Control": "public, no-cache"}
    if etag_matches(if_none_match, etag):
        return Response(status_code=304, headers=headers)
    response.headers.update(headers)
    return response
