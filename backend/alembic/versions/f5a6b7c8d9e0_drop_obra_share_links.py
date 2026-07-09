"""drop obra_share_links: reemplazado por descarga directa (sin link público)

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-07-09

El link solo-lectura por token para el comitente se reemplazó por descarga
directa del PDF (autenticada, ?audience=comitente) — el contratista baja el
archivo y lo reenvía él mismo, sin exponer una URL pública.
"""
from alembic import op
import sqlalchemy as sa

revision = "f5a6b7c8d9e0"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_obra_share_links_token", table_name="obra_share_links")
    op.drop_table("obra_share_links")


def downgrade() -> None:
    op.create_table(
        "obra_share_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_obra_share_links_token", "obra_share_links", ["token"], unique=True)
