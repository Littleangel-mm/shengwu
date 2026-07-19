"""Index extraction-linked conversion records."""

from alembic import op

revision = "20260719_004"
down_revision = "20260719_003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_conversion_records_extraction_record",
        "conversion_records",
        ["extraction_record_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversion_records_extraction_record",
        table_name="conversion_records",
    )
