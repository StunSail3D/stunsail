"""Record Agent credential revocation.

Revision ID: 0004_agent_revocation
Revises: 0003_currency_settings
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_agent_revocation"
down_revision = "0003_currency_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents", sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false())
    )


def downgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("revoked")
