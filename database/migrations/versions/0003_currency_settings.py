"""Store a shared default currency without changing historical prices.

Revision ID: 0003_currency_settings
Revises: 0002_core_schema
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_currency_settings"
down_revision = "0002_core_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "currency_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_currency_settings_singleton"),
    )


def downgrade() -> None:
    op.drop_table("currency_settings")
