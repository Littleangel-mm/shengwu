import pytest
from fastapi.routing import APIRoute
from pydantic import ValidationError

from app.api.v1.extractions import router
from app.schemas.workflow import ExtractionRecordReview
from app.services.extraction import ExtractionService, first_not_none, parse_numeric


def test_parse_single_number() -> None:
    assert parse_numeric("12.5") == {"type": "number", "value": 12.5}


def test_parse_range_preserves_limits() -> None:
    assert parse_numeric("10~20") == {"type": "range", "min": 10.0, "max": 20.0, "mid": 15.0}


def test_parse_mean_and_standard_deviation() -> None:
    assert parse_numeric("3.25 ± 0.12") == {"type": "mean_sd", "mean": 3.25, "sd": 0.12}


def test_zero_is_not_treated_as_missing() -> None:
    parsed = parse_numeric("0")
    assert first_not_none(parsed.get("value"), parsed.get("mean"), parsed.get("mid")) == 0.0


def test_review_accepts_supported_status_and_editable_values() -> None:
    payload = ExtractionRecordReview(
        review_status="modified",
        normalized_value={"value": 0},
        ml_value={"value": 0},
        notes="人工核验为零",
    )
    assert payload.review_status == "modified"
    assert payload.normalized_value == {"value": 0}


@pytest.mark.parametrize("status", ["confirmed", "modified", "doubtful", "excluded"])
def test_review_statuses(status: str) -> None:
    payload = ExtractionRecordReview.model_validate({"review_status": status})
    assert payload.review_status == status


def test_review_rejects_raw_value_changes() -> None:
    with pytest.raises(ValidationError):
        ExtractionRecordReview.model_validate(
            {"review_status": "confirmed", "raw_value": "tampered"}
        )


def test_extraction_review_and_summary_routes_are_registered() -> None:
    routes = {
        (route.path, method)
        for route in router.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    assert (
        "/{project_id}/extraction-runs/{run_id}/summary",
        "GET",
    ) in routes
    assert (
        "/{project_id}/extraction-runs/{run_id}/records/{record_id}",
        "PATCH",
    ) in routes


def test_dimension_metadata_keeps_legacy_keys_and_conditions() -> None:
    text = "treatment: control at 24 h, 37°C, pH 6.5 and 180 rpm"
    group_key, timepoint = ExtractionService._dimension_keys(text, "block=1")
    dimensions = ExtractionService._dimension_metadata(text)

    assert "treatment=control" in group_key
    assert timepoint == "24h"
    assert dimensions == {
        "treatment": "control",
        "timepoint": "24h",
        "experimental_conditions": {
            "temperature": "37°C",
            "ph": "pH 6.5",
            "agitation": "180 rpm",
        },
    }
