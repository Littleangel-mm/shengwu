"""Add PRISMA flow records for systematic-review projects."""

from alembic import op

revision = "20260719_005"
down_revision = "20260719_004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE prisma_flows (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id   uuid NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
            data         jsonb NOT NULL DEFAULT '{}'::jsonb,
            notes        text,
            updated_by   uuid REFERENCES app_users(id) ON DELETE SET NULL,
            created_at   timestamptz NOT NULL DEFAULT now(),
            updated_at   timestamptz NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS prisma_flows;")
