"""client web apps: published_url, client_api_key, deploy_webhook_url

Revision ID: d3f1a2b4c5e6
Revises: 02bd6c816f98
Create Date: 2026-09-11
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'd3f1a2b4c5e6'
down_revision: str | None = '02bd6c816f98'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('services', sa.Column('published_url', sa.String(length=500), server_default='', nullable=False))
    op.add_column('services', sa.Column('client_api_key', sa.String(length=64), server_default='', nullable=False))
    op.add_column('services', sa.Column('deploy_webhook_url', sa.String(length=500), server_default='', nullable=False))
    op.create_index('ix_services_client_api_key', 'services', ['client_api_key'])


def downgrade() -> None:
    op.drop_index('ix_services_client_api_key', table_name='services')
    op.drop_column('services', 'deploy_webhook_url')
    op.drop_column('services', 'client_api_key')
    op.drop_column('services', 'published_url')
