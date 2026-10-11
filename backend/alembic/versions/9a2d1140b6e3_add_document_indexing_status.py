"""add document indexing status

Revision ID: 9a2d1140b6e3
Revises: 18e815e6eed1
Create Date: 2026-10-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "9a2d1140b6e3"
down_revision: Union[str, Sequence[str], None] = "18e815e6eed1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "indexing_status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "documents",
        sa.Column("indexing_error", sa.String(length=300), nullable=True),
    )
    op.create_check_constraint(
        "ck_documents_indexing_status",
        "documents",
        "indexing_status IN ('pending', 'processing', 'completed', 'failed')",
    )
    op.create_unique_constraint(
        "uq_documents_id_user_id",
        "documents",
        ["id", "user_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_documents_id_user_id", "documents", type_="unique")
    op.drop_constraint(
        "ck_documents_indexing_status",
        "documents",
        type_="check",
    )
    op.drop_column("documents", "indexing_error")
    op.drop_column("documents", "indexing_status")
