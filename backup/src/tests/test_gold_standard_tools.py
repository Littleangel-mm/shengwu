import json
from pathlib import Path

import pytest

from scripts.gold_standard_evaluate import evaluate, render_markdown
from scripts.gold_standard_import import build_import_bundle, validate_payload
from scripts.gold_standard_manifest import (
    build_manifest,
    manifest_digest,
    verify_manifest,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "gold_standard"


def _fixture(name: str) -> dict[str, object]:
    value = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_manifest_build_and_verify_detects_file_tampering(tmp_path: Path) -> None:
    sample = tmp_path / "expected.json"
    sample.write_text('{"sample": true}\n', encoding="utf-8")

    manifest = build_manifest(tmp_path, [Path("expected.json")])

    assert manifest["manifest_sha256"] == manifest_digest(manifest)
    assert verify_manifest(manifest, tmp_path) == []
    sample.write_text('{"sample": false}\n', encoding="utf-8")
    issues = verify_manifest(manifest, tmp_path)
    assert "文件大小不匹配: expected.json" in issues
    assert "SHA-256 不匹配: expected.json" in issues


def test_manifest_detects_manifest_digest_tampering(tmp_path: Path) -> None:
    sample = tmp_path / "sample.txt"
    sample.write_text("sample", encoding="utf-8")
    manifest = build_manifest(tmp_path, [sample])
    manifest["schema_version"] = "changed"

    issues = verify_manifest(manifest, tmp_path)

    assert "manifest_sha256 不匹配" in issues
    assert any(issue.startswith("不支持的 schema_version") for issue in issues)


def test_manifest_rejects_file_outside_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-gold-standard.txt"
    outside.write_text("not in root", encoding="utf-8")
    try:
        with pytest.raises(ValueError, match="不在金标准目录内"):
            build_manifest(tmp_path, [outside])
    finally:
        outside.unlink()


def test_import_payload_validation_and_bundle_notice() -> None:
    expected = _fixture("expected.json")
    actual = _fixture("actual.json")
    manifest = {"manifest_sha256": "a" * 64}

    assert validate_payload(expected, "expected") == []
    bundle = build_import_bundle(manifest, expected, actual)

    assert bundle["source_manifest_sha256"] == "a" * 64
    assert bundle["expected"] == expected
    assert "不代表客户真实准确率" in str(bundle["notice"])


def test_import_payload_rejects_duplicate_and_invalid_ids() -> None:
    payload = {
        "fields": [
            {"id": "duplicate"},
            {"id": "duplicate"},
            {"value": "missing id"},
        ]
    }

    issues = validate_payload(payload, "expected")

    assert "expected.fields 存在重复 id: duplicate" in issues
    assert "expected.fields[2].id 必须是非空字符串" in issues


def test_evaluate_synthetic_fixture_scores_all_dimensions() -> None:
    report = evaluate(_fixture("expected.json"), _fixture("actual.json"))

    assert report["customer_accuracy_claimed"] is False
    metrics = report["metrics"]
    for name in (
        "parsing_completeness",
        "field_accuracy",
        "numeric_tolerance_accuracy",
        "association_accuracy",
        "table_structure_accuracy",
    ):
        assert metrics[name] == {"matched": 1, "total": 2, "score": 0.5}
    assert metrics["translation_reference_score"]["matched"] == 1
    assert metrics["translation_reference_score"]["total"] == 2
    assert len(report["issues"]) == 6
    assert {issue["category"] for issue in report["issues"]} == {
        "parsing",
        "field",
        "numeric",
        "association",
        "table",
        "translation",
    }


def test_evaluate_supports_relative_tolerance_and_reports_extras() -> None:
    expected = {"numbers": [{"id": "n1", "value": 100.0, "relative_tolerance": 0.02}]}
    actual = {
        "numbers": [
            {"id": "n1", "value": 101.9},
            {"id": "extra", "value": 1},
        ]
    }

    report = evaluate(expected, actual)

    assert report["metrics"]["numeric_tolerance_accuracy"]["score"] == 1.0
    assert any(issue["category"] == "unexpected" for issue in report["issues"])


def test_evaluate_empty_sections_are_not_reported_as_perfect() -> None:
    report = evaluate({}, {})

    assert all(metric["score"] is None for metric in report["metrics"].values())
    assert report["issues"] == []


def test_render_markdown_contains_metrics_issues_and_disclaimer() -> None:
    report = evaluate(_fixture("expected.json"), _fixture("actual.json"))

    markdown = render_markdown(report)

    assert "# 金标准评估问题清单" in markdown
    assert "不得据此声称客户真实准确率" in markdown
    assert "| 数值容差准确率 | 1 | 2 | 0.5000 |" in markdown
    assert "association-wrong" in markdown
