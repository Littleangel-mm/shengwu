import hashlib
import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from app.services.dataset import _freeze_issues, _freeze_snapshot, _has_dataset_value


def test_required_and_doubtful_cells_block_freeze_with_structured_issues() -> None:
    field_id = uuid4()
    doubtful_field_id = uuid4()
    row_id = uuid4()
    doubtful_cell_id = uuid4()
    fields = [
        {
            "id": field_id,
            "field_key": "required_value",
            "display_name": "Required value",
            "is_required": True,
        },
        {
            "id": doubtful_field_id,
            "field_key": "review_value",
            "display_name": "Review value",
            "is_required": False,
        },
    ]
    rows = [{"id": row_id, "row_no": 1, "row_key": "row-1"}]
    cells = [
        {
            "id": doubtful_cell_id,
            "row_id": row_id,
            "field_id": doubtful_field_id,
            "value_number": 0,
            "is_missing": False,
            "review_status": "doubtful",
        }
    ]

    issues = _freeze_issues(fields, rows, cells)

    assert [issue["code"] for issue in issues] == [
        "required_value_missing",
        "doubtful_value",
    ]
    assert issues[0]["row_key"] == "row-1"
    assert issues[0]["field_key"] == "required_value"
    assert issues[1]["cell_id"] == str(doubtful_cell_id)


def test_zero_and_false_are_valid_required_values() -> None:
    assert _has_dataset_value({"value_number": 0, "is_missing": False})
    assert _has_dataset_value({"value_boolean": False, "is_missing": False})
    assert not _has_dataset_value({"value_number": 0, "is_missing": True})


def test_freeze_snapshot_covers_typed_review_and_provenance_values() -> None:
    field_id = uuid4()
    row_id = uuid4()
    cell_id = uuid4()
    fields = [
        {
            "id": field_id,
            "field_key": "yield",
            "display_name": "Yield",
            "data_type": "number",
            "semantic_role": "target",
            "unit_id": uuid4(),
            "position": 0,
            "is_required": True,
            "is_hidden": False,
            "validation_rules": {},
            "display_config": {},
            "metadata": {},
        }
    ]
    rows = [
        {
            "id": row_id,
            "row_no": 1,
            "row_key": "sample-1",
            "source_document_id": uuid4(),
            "source_document_version_id": uuid4(),
            "source_sample_key": "source-1",
            "review_status": "confirmed",
            "metadata": {},
        }
    ]
    cell = {
        "id": cell_id,
        "row_id": row_id,
        "field_id": field_id,
        "source_extraction_record_id": uuid4(),
        "raw_value": "42",
        "raw_unit_text": "%",
        "normalized_value": {"value": 42},
        "ml_value": {"value": 0.42},
        "value_text": None,
        "value_number": 42,
        "value_boolean": None,
        "value_date": None,
        "value_json": None,
        "range_min": None,
        "range_max": None,
        "mean_value": None,
        "standard_deviation": None,
        "significance_marker": None,
        "unit_id": uuid4(),
        "value_source": "manual",
        "review_status": "confirmed",
        "confidence": 0.9,
        "is_missing": False,
        "is_image_estimate": False,
        "is_manually_modified": True,
        "notes": "checked",
        "metadata": {},
    }
    evidence = [
        {
            "dataset_cell_id": cell_id,
            "extraction_evidence_id": uuid4(),
            "document_version_id": uuid4(),
            "page_id": uuid4(),
            "block_id": uuid4(),
            "table_cell_id": None,
            "figure_id": None,
            "evidence_text": "yield was 42%",
            "bbox": {"x": 1},
            "is_primary": True,
        }
    ]
    snapshot = _freeze_snapshot(fields, rows, [cell], evidence)
    digest = hashlib.sha256(
        json.dumps(snapshot, default=str, sort_keys=True).encode()
    ).hexdigest()

    changed = {**cell, "notes": "rechecked"}
    changed_snapshot = _freeze_snapshot(fields, rows, [changed], evidence)
    changed_digest = hashlib.sha256(
        json.dumps(changed_snapshot, default=str, sort_keys=True).encode()
    ).hexdigest()

    assert snapshot["cells"][0]["value_number"] == 42
    assert snapshot["cells"][0]["normalized_value"] == {"value": 42}
    assert snapshot["cells"][0]["ml_value"] == {"value": 0.42}
    assert snapshot["cells"][0]["review_status"] == "confirmed"
    assert snapshot["evidence"][0]["evidence_text"] == "yield was 42%"
    assert digest != changed_digest


def test_dataset_routes_include_version_chain_and_require_download_authentication() -> None:
    paths = app.openapi()["paths"]
    assert "/api/v1/projects/{project_id}/datasets/{dataset_id}/versions" in paths

    client = TestClient(app)
    project_id = uuid4()
    version_id = uuid4()
    export_response = client.get(
        f"/api/v1/projects/{project_id}/dataset-versions/{version_id}/export.xlsx"
    )
    clone_response = client.post(
        f"/api/v1/projects/{project_id}/dataset-versions/{version_id}/clone",
        json={"change_summary": "review"},
    )

    assert export_response.status_code == 401
    assert export_response.json()["error"]["code"] == "authentication_required"
    assert clone_response.status_code == 401


def test_evidence_immutability_exists_in_migration_and_both_initial_schemas() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    repository_root = backend_root.parents[1]
    paths = [
        backend_root
        / "migrations"
        / "versions"
        / "20260719_003_dataset_evidence_immutability.py",
        backend_root / "migrations" / "sql" / "001_initial_schema.sql",
        repository_root / "sql" / "001_initial_schema.sql",
    ]

    for path in paths:
        sql = path.read_text(encoding="utf-8")
        assert "ensure_dataset_evidence_mutable" in sql
        assert "BEFORE INSERT OR UPDATE OR DELETE ON dataset_cell_evidence" in sql
        assert "frozen" in sql and "archived" in sql
