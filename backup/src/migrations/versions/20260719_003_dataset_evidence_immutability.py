"""Prevent evidence mutation on frozen dataset versions."""

from alembic import op

revision = "20260719_003"
down_revision = "20260719_002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ensure_dataset_evidence_mutable()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            source_cell_id uuid;
            target_cell_id uuid;
            source_status varchar(32);
            target_status varchar(32);
        BEGIN
            IF TG_OP IN ('UPDATE', 'DELETE') THEN
                source_cell_id := OLD.dataset_cell_id;
                SELECT dv.status INTO source_status
                FROM dataset_cells dc
                JOIN dataset_rows dr ON dr.id = dc.row_id
                JOIN dataset_versions dv ON dv.id = dr.dataset_version_id
                WHERE dc.id = source_cell_id;
            END IF;

            IF TG_OP IN ('INSERT', 'UPDATE') THEN
                target_cell_id := NEW.dataset_cell_id;
                SELECT dv.status INTO target_status
                FROM dataset_cells dc
                JOIN dataset_rows dr ON dr.id = dc.row_id
                JOIN dataset_versions dv ON dv.id = dr.dataset_version_id
                WHERE dc.id = target_cell_id;
            END IF;

            IF source_status IN ('frozen', 'archived')
               OR target_status IN ('frozen', 'archived') THEN
                RAISE EXCEPTION 'Dataset evidence is immutable for frozen or archived versions';
            END IF;

            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE TRIGGER trg_dataset_cell_evidence_mutable
        BEFORE INSERT OR UPDATE OR DELETE ON dataset_cell_evidence
        FOR EACH ROW EXECUTE FUNCTION ensure_dataset_evidence_mutable();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_dataset_cell_evidence_mutable ON dataset_cell_evidence;
        DROP FUNCTION IF EXISTS ensure_dataset_evidence_mutable();
        """
    )
