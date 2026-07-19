"""Add persistent login throttling state."""

from alembic import op

revision = "20260719_002"
down_revision = "20260719_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_login_attempts (
            key_hash char(64) PRIMARY KEY,
            failed_count integer NOT NULL DEFAULT 0 CHECK (failed_count >= 0),
            window_started_at timestamptz NOT NULL DEFAULT now(),
            blocked_until timestamptz,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_auth_login_attempts_key
                CHECK (key_hash ~ '^[0-9a-f]{64}$')
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_auth_login_attempts_blocked_until
            ON auth_login_attempts(blocked_until)
            WHERE blocked_until IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS auth_login_attempts")
