"""create moderation schema

Revision ID: 0001
Revises: None
"""
import sqlalchemy as sa

from alembic import op

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('channels',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('youtube_channel_id', sa.String(length=24), nullable=False),
    sa.Column('handle', sa.String(length=100), nullable=True),
    sa.Column('status', sa.String(length=20), server_default='unreviewed', nullable=False),
    sa.Column('score', sa.Numeric(precision=12, scale=4), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("handle IS NULL OR (left(handle, 1) = '@' AND length(handle) > 1)", name=op.f('ck_channels_handle')),
    sa.CheckConstraint("score >= 0 AND score < 'Infinity'::numeric", name=op.f('ck_channels_score')),
    sa.CheckConstraint("status IN ('unreviewed', 'pending_review', 'approved', 'rejected')", name=op.f('ck_channels_status')),
    sa.CheckConstraint("youtube_channel_id ~ '^UC[A-Za-z0-9_-]{22}$'", name=op.f('ck_channels_youtube_id')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_channels')),
    sa.UniqueConstraint('youtube_channel_id', name=op.f('uq_channels_youtube_channel_id'))
    )
    op.create_index('ix_channels_handle_lower', 'channels', [sa.literal_column('lower(handle)')], unique=False)
    op.create_index('ix_channels_status_updated_at', 'channels', ['status', 'updated_at'], unique=False)
    op.create_index('ix_channels_updated_at_id', 'channels', ['updated_at', 'id'], unique=False)
    op.create_table('installs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('reputation', sa.Numeric(precision=12, scale=4), server_default='1', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("reputation >= 0 AND reputation < 'Infinity'::numeric", name=op.f('ck_installs_reputation')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_installs'))
    )
    op.create_table('appeals',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('channel_id', sa.Uuid(), nullable=False),
    sa.Column('install_id', sa.Uuid(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='open', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("(status = 'open' AND resolved_at IS NULL) OR (status <> 'open' AND resolved_at IS NOT NULL)", name=op.f('ck_appeals_resolution')),
    sa.CheckConstraint("status IN ('open', 'accepted', 'rejected')", name=op.f('ck_appeals_status')),
    sa.CheckConstraint('length(btrim(reason)) BETWEEN 1 AND 2000', name=op.f('ck_appeals_reason')),
    sa.ForeignKeyConstraint(['channel_id'], ['channels.id'], name=op.f('fk_appeals_channel_id_channels'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['install_id'], ['installs.id'], name=op.f('fk_appeals_install_id_installs'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_appeals')),
    sa.UniqueConstraint('id', 'channel_id', name='uq_appeals_id_channel')
    )
    op.create_index('ix_appeals_channel_id', 'appeals', ['channel_id'], unique=False)
    op.create_index('ix_appeals_install_id', 'appeals', ['install_id'], unique=False)
    op.create_index('ix_appeals_status_created_at', 'appeals', ['status', 'created_at'], unique=False)
    op.create_table('reports',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('channel_id', sa.Uuid(), nullable=False),
    sa.Column('install_id', sa.Uuid(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('length(btrim(reason)) BETWEEN 1 AND 2000', name=op.f('ck_reports_reason')),
    sa.ForeignKeyConstraint(['channel_id'], ['channels.id'], name=op.f('fk_reports_channel_id_channels'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['install_id'], ['installs.id'], name=op.f('fk_reports_install_id_installs'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reports')),
    sa.UniqueConstraint('install_id', 'channel_id', name='uq_reports_install_channel')
    )
    op.create_index('ix_reports_channel_id_created_at', 'reports', ['channel_id', 'created_at'], unique=False)
    op.create_table('moderation_actions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('channel_id', sa.Uuid(), nullable=False),
    sa.Column('appeal_id', sa.Uuid(), nullable=True),
    sa.Column('action', sa.String(length=20), nullable=False),
    sa.Column('actor', sa.String(length=100), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(action IN ('accept_appeal', 'reject_appeal') AND appeal_id IS NOT NULL) OR (action IN ('approve', 'reject') AND appeal_id IS NULL)", name=op.f('ck_moderation_actions_appeal_action')),
    sa.CheckConstraint("action IN ('approve', 'reject', 'accept_appeal', 'reject_appeal')", name=op.f('ck_moderation_actions_action')),
    sa.CheckConstraint('length(btrim(actor)) > 0', name=op.f('ck_moderation_actions_actor')),
    sa.CheckConstraint('length(btrim(reason)) BETWEEN 1 AND 2000', name=op.f('ck_moderation_actions_reason')),
    sa.ForeignKeyConstraint(['appeal_id', 'channel_id'], ['appeals.id', 'appeals.channel_id'], name='fk_moderation_actions_appeal_channel', ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['channel_id'], ['channels.id'], name=op.f('fk_moderation_actions_channel_id_channels'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_moderation_actions'))
    )
    op.create_index('ix_moderation_actions_appeal_id', 'moderation_actions', ['appeal_id'], unique=False)
    op.create_index('ix_moderation_actions_channel_id_created_at', 'moderation_actions', ['channel_id', 'created_at'], unique=False)

    # Database-owned timestamp updates also cover direct SQL moderation changes.
    op.execute("""
        CREATE FUNCTION touch_channel_updated_at() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at = clock_timestamp();
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER channels_touch_updated_at
        BEFORE UPDATE ON channels
        FOR EACH ROW EXECUTE FUNCTION touch_channel_updated_at()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER channels_touch_updated_at ON channels")
    op.execute("DROP FUNCTION touch_channel_updated_at()")
    op.drop_index('ix_moderation_actions_channel_id_created_at', table_name='moderation_actions')
    op.drop_index('ix_moderation_actions_appeal_id', table_name='moderation_actions')
    op.drop_table('moderation_actions')
    op.drop_index('ix_reports_channel_id_created_at', table_name='reports')
    op.drop_table('reports')
    op.drop_index('ix_appeals_status_created_at', table_name='appeals')
    op.drop_index('ix_appeals_install_id', table_name='appeals')
    op.drop_index('ix_appeals_channel_id', table_name='appeals')
    op.drop_table('appeals')
    op.drop_table('installs')
    op.drop_index('ix_channels_updated_at_id', table_name='channels')
    op.drop_index('ix_channels_status_updated_at', table_name='channels')
    op.drop_index('ix_channels_handle_lower', table_name='channels')
    op.drop_table('channels')
