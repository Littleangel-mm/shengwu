from app.services.extraction import parse_numeric


def test_parse_single_number() -> None:
    assert parse_numeric("12.5") == {"type": "number", "value": 12.5}


def test_parse_range_preserves_limits() -> None:
    assert parse_numeric("10~20") == {"type": "range", "min": 10.0, "max": 20.0, "mid": 15.0}


def test_parse_mean_and_standard_deviation() -> None:
    assert parse_numeric("3.25 ± 0.12") == {"type": "mean_sd", "mean": 3.25, "sd": 0.12}
