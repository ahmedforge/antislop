"""Allow one open appeal per installation and channel.

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No public appeal writes existed before Stage 7. If an operator manually
    # inserted duplicates, fail rather than silently discard their review history.
    op.create_index("uq_appeals_open_install_channel", "appeals", ["install_id", "channel_id"],
                    unique=True, postgresql_where=sa.text("status = 'open' AND install_id IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("uq_appeals_open_install_channel", table_name="appeals")
