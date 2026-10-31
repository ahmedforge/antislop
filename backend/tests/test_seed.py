"""Validate the explicit seed tool's all-or-nothing behavior and CLI."""
import json

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.models import Channel, ModerationAction
from app.seed import main, seed_channels


@pytest.mark.parametrize("failure", ["duplicate", "malformed", "audit"])
def test_seed_failure_writes_no_channels_or_audit(migrated_db, tmp_path, failure):
    engine, _ = migrated_db
    source = tmp_path / "seed.json"
    entry = {"youtube_channel_id": "UC" + "z" * 22, "reason": "Reviewed fixture"}
    source.write_text(json.dumps([entry, entry] if failure == "duplicate" else [entry]))
    error = ValueError
    if failure == "malformed":
        source.write_text('{"incomplete":')
    if failure == "audit":
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE moderation_actions ADD CONSTRAINT test_fail CHECK (false)"))
        error = IntegrityError
    with pytest.raises(error):
        seed_channels(engine, source)
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(Channel)) == 0
        assert connection.scalar(select(func.count()).select_from(ModerationAction)) == 0


def test_seed_cli_reports_inserted_count_and_idempotent_retry(migrated_db, tmp_path, monkeypatch, capsys):
    source = tmp_path / "seed.json"
    source.write_text(json.dumps([{"youtube_channel_id": "UC" + "z" * 22, "reason": "Reviewed fixture"}]))
    monkeypatch.setattr("sys.argv", ["app.seed", str(source)])
    main()
    assert "Inserted 1 approved channel(s)" in capsys.readouterr().out
    main()
    assert "Inserted 0 approved channel(s)" in capsys.readouterr().out
