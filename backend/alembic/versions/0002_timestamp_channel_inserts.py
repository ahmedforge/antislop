"""Timestamp inserts after write-lock acquisition for safe delta snapshots.

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TRIGGER channels_touch_updated_at ON channels")
    op.execute("""
        CREATE TRIGGER channels_touch_updated_at
        BEFORE INSERT OR UPDATE ON channels
        FOR EACH ROW EXECUTE FUNCTION touch_channel_updated_at()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER channels_touch_updated_at ON channels")
    op.execute("""
        CREATE TRIGGER channels_touch_updated_at
        BEFORE UPDATE ON channels
        FOR EACH ROW EXECUTE FUNCTION touch_channel_updated_at()
    """)
