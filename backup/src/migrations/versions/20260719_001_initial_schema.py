"""Initial generic research platform schema."""

from pathlib import Path
from typing import Any, cast

from alembic import op

revision = "20260719_001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql_path = Path(__file__).resolve().parents[1] / "sql" / "001_initial_schema.sql"
    sql = sql_path.read_text(encoding="utf-8")
    sql = sql.replace("BEGIN;", "", 1).rsplit("COMMIT;", 1)[0]
    connection = op.get_bind()
    raw_connection = cast(Any, connection.connection)
    cursor = raw_connection.cursor()
    cursor.execute(sql)


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql("DROP SCHEMA public CASCADE")
    connection.exec_driver_sql("CREATE SCHEMA public")
