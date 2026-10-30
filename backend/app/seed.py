"""Explicit, transactional seed import: python -m app.seed path/to/seed.json."""
import argparse
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from sqlalchemy import insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine

from app.config import Settings
from app.db import make_engine
from app.models import Channel, ModerationAction


class SeedChannel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    youtube_channel_id: str = Field(pattern=r"^UC[A-Za-z0-9_-]{22}$")
    handle: str | None = Field(default=None, min_length=2, max_length=100, pattern=r"^@.+$")
    reason: str = Field(min_length=1, max_length=2000)


def seed_channels(engine: Engine, source: Path) -> int:
    # Validate the entire file before writing anything.
    entries = TypeAdapter(list[SeedChannel]).validate_python(json.loads(source.read_text()))
    if len({entry.youtube_channel_id for entry in entries}) != len(entries):
        raise ValueError("Seed file contains duplicate channel IDs")
    count = 0
    with engine.begin() as connection:
        for entry in entries:
            channel_id = connection.scalar(
                pg_insert(Channel).values(
                    youtube_channel_id=entry.youtube_channel_id,
                    handle=entry.handle, status="approved",
                ).on_conflict_do_nothing(index_elements=["youtube_channel_id"]).returning(Channel.id)
            )
            if channel_id is not None:
                connection.execute(insert(ModerationAction).values(
                    channel_id=channel_id, action="approve", actor="seed-import", reason=entry.reason,
                ))
                count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Import explicitly reviewed channels; existing channels are never overwritten.")
    parser.add_argument("source", type=Path, help="JSON array of reviewed channels")
    args = parser.parse_args()
    engine = make_engine(Settings())
    try:
        count = seed_channels(engine, args.source)
        print(f"Inserted {count} approved channel(s); existing channels left unchanged.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
