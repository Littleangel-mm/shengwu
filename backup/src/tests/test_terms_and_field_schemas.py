from collections import Counter
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import Column, MetaData, Table
from sqlalchemy.dialects.postgresql import UUID

from app.core.errors import AppError
from app.models import ProcessingJob
from app.schemas.workflow import FieldDefinitionInput, FieldSchemaUpdate, TermUpdate
from app.services.term import TermService
from app.worker import JobWorker


def test_term_update_supports_full_edit_and_alias_replacement() -> None:
    category_id = uuid4()
    payload = TermUpdate.model_validate(
        {
            "category_id": str(category_id),
            "definition": "updated",
            "language": "zh-CN",
            "data_type": "number",
            "semantic_role": "target",
            "aliases": ["别名", "Alias"],
        }
    )

    assert payload.category_id == category_id
    assert payload.definition == "updated"
    assert payload.language == "zh-CN"
    assert payload.data_type == "number"
    assert payload.semantic_role == "target"
    assert payload.aliases == ["别名", "Alias"]


def test_discovery_candidate_limits_are_applied() -> None:
    counter = Counter({"alpha": 8, "beta": 5, "gamma": 3, "delta": 1})

    assert TermService._discovery_candidates(counter, 4, 2) == [("alpha", 8), ("beta", 5)]
    assert TermService._discovery_candidates(counter, 6, 10) == [("alpha", 8)]


def test_worker_forwards_discovery_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    search_run_id = uuid4()
    discover = MagicMock(return_value={"candidate_count": 0})
    service = MagicMock()
    service.discover = discover
    monkeypatch.setattr("app.services.term.TermService", MagicMock(return_value=service))
    progress = MagicMock()
    job = cast(
        ProcessingJob,
        SimpleNamespace(
            job_type="discover_terms",
            requested_config={
                "search_run_id": str(search_run_id),
                "min_occurrences": 7,
                "max_candidates": 42,
            },
        ),
    )

    result = JobWorker.__new__(JobWorker)._dispatch(MagicMock(), job, progress)

    assert result == {"candidate_count": 0}
    discover.assert_called_once_with(
        search_run_id,
        progress,
        min_occurrences=7,
        max_candidates=42,
    )


def test_field_schema_update_is_a_full_replacement_payload() -> None:
    payload = FieldSchemaUpdate.model_validate(
        {
            "name": "Updated schema",
            "settings": {"strict": True},
            "fields": [{"field_key": "yield", "display_name": "Yield"}],
        }
    )

    assert payload.name == "Updated schema"
    assert payload.settings == {"strict": True}
    assert payload.fields[0].field_key == "yield"

    with pytest.raises(ValueError):
        FieldSchemaUpdate.model_validate({"name": "Incomplete", "settings": {}})


def test_field_schema_rejects_duplicate_keys_before_writing() -> None:
    service = TermService(MagicMock())
    fields = [
        FieldDefinitionInput(field_key="temperature", display_name="Temperature"),
        FieldDefinitionInput(field_key="temperature", display_name="Temperature duplicate"),
    ]

    with pytest.raises(AppError) as exc_info:
        service._validate_field_inputs(uuid4(), fields)

    assert exc_info.value.code == "field_key_duplicate"


def test_field_schema_rejects_source_term_from_another_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = MetaData()
    terms = Table(
        "terms",
        metadata,
        Column("id", UUID(as_uuid=True)),
        Column("project_id", UUID(as_uuid=True)),
        Column("deleted_at"),
    )
    db = MagicMock()
    db.scalars.return_value.all.return_value = []
    monkeypatch.setattr("app.services.term.table", lambda _db, _name: terms)
    service = TermService(db)
    field = FieldDefinitionInput(
        field_key="temperature",
        display_name="Temperature",
        source_term_id=uuid4(),
    )

    with pytest.raises(AppError) as exc_info:
        service._validate_field_inputs(uuid4(), [field])

    assert exc_info.value.code == "field_source_term_invalid"
