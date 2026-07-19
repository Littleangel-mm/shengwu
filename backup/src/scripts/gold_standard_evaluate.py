import argparse
import json
import math
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

SECTIONS = ("documents", "fields", "numbers", "associations", "tables", "translations")


def _normalized_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value).strip()).casefold()


def _records_by_id(payload: dict[str, Any], section: str) -> dict[str, dict[str, Any]]:
    records = payload.get(section, [])
    if not isinstance(records, list):
        raise ValueError(f"{section} 必须是数组")
    indexed: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(records):
        if not isinstance(record, dict) or not isinstance(record.get("id"), str):
            raise ValueError(f"{section}[{index}] 缺少字符串 id")
        record_id = record["id"]
        if record_id in indexed:
            raise ValueError(f"{section} 存在重复 id: {record_id}")
        indexed[record_id] = record
    return indexed


def _metric(matched: int, total: int) -> dict[str, int | float | None]:
    return {
        "matched": matched,
        "total": total,
        "score": matched / total if total else None,
    }


def _issue(
    category: str,
    record_id: str,
    reason: str,
    expected: Any,
    actual: Any,
) -> dict[str, Any]:
    return {
        "category": category,
        "id": record_id,
        "reason": reason,
        "expected": expected,
        "actual": actual,
    }


def _evaluate_documents(
    expected: dict[str, dict[str, Any]],
    actual: dict[str, dict[str, Any]],
) -> tuple[dict[str, int | float | None], list[dict[str, Any]]]:
    matched = 0
    issues: list[dict[str, Any]] = []
    for record_id in expected:
        observed = actual.get(record_id)
        if observed and observed.get("parsed") is True and observed.get("evidence_locatable") is True:
            matched += 1
        else:
            issues.append(
                _issue(
                    "parsing",
                    record_id,
                    "文档未成功解析或证据不可定位",
                    {"parsed": True, "evidence_locatable": True},
                    observed,
                )
            )
    return _metric(matched, len(expected)), issues


def _evaluate_fields(
    expected: dict[str, dict[str, Any]],
    actual: dict[str, dict[str, Any]],
) -> tuple[dict[str, int | float | None], list[dict[str, Any]]]:
    matched = 0
    issues: list[dict[str, Any]] = []
    for record_id, target in expected.items():
        observed = actual.get(record_id)
        target_value = target.get("value")
        observed_value = observed.get("value") if observed else None
        if observed is not None and _normalized_text(target_value) == _normalized_text(observed_value):
            matched += 1
        else:
            issues.append(
                _issue("field", record_id, "字段值不匹配", target_value, observed_value)
            )
    return _metric(matched, len(expected)), issues


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _evaluate_numbers(
    expected: dict[str, dict[str, Any]],
    actual: dict[str, dict[str, Any]],
) -> tuple[dict[str, int | float | None], list[dict[str, Any]]]:
    matched = 0
    issues: list[dict[str, Any]] = []
    for record_id, target in expected.items():
        observed = actual.get(record_id)
        target_value = _number(target.get("value"))
        observed_value = _number(observed.get("value")) if observed else None
        tolerance = _number(target.get("tolerance", 0))
        relative = _number(target.get("relative_tolerance", 0))
        target_unit = _normalized_text(target.get("unit", ""))
        observed_unit = _normalized_text(observed.get("unit", "")) if observed else ""
        allowed: float | None = None
        if (
            target_value is not None
            and tolerance is not None
            and relative is not None
            and tolerance >= 0
            and relative >= 0
        ):
            allowed = max(tolerance, abs(target_value) * relative)
        if (
            allowed is not None
            and target_value is not None
            and observed_value is not None
            and abs(observed_value - target_value) <= allowed
            and target_unit == observed_unit
        ):
            matched += 1
        else:
            issues.append(
                _issue(
                    "numeric",
                    record_id,
                    "数值超出容差、单位不匹配或配置无效",
                    {
                        "value": target.get("value"),
                        "unit": target.get("unit"),
                        "allowed_error": allowed,
                    },
                    observed,
                )
            )
    return _metric(matched, len(expected)), issues


def _evaluate_associations(
    expected: dict[str, dict[str, Any]],
    actual: dict[str, dict[str, Any]],
) -> tuple[dict[str, int | float | None], list[dict[str, Any]]]:
    keys = ("treatment_group", "timepoint", "condition")
    matched = 0
    issues: list[dict[str, Any]] = []
    for record_id, target in expected.items():
        observed = actual.get(record_id)
        is_match = observed is not None and all(
            _normalized_text(target.get(key, "")) == _normalized_text(observed.get(key, ""))
            for key in keys
        )
        if is_match:
            matched += 1
        else:
            issues.append(
                _issue(
                    "association",
                    record_id,
                    "处理组、时间点或实验条件关联不匹配",
                    {key: target.get(key) for key in keys},
                    {key: observed.get(key) for key in keys} if observed else None,
                )
            )
    return _metric(matched, len(expected)), issues


def _evaluate_tables(
    expected: dict[str, dict[str, Any]],
    actual: dict[str, dict[str, Any]],
) -> tuple[dict[str, int | float | None], list[dict[str, Any]]]:
    keys = ("headers", "merged_cells", "footnotes", "cells")
    matched = 0
    issues: list[dict[str, Any]] = []
    for record_id, target in expected.items():
        observed = actual.get(record_id)
        if observed is not None and all(target.get(key, []) == observed.get(key, []) for key in keys):
            matched += 1
        else:
            issues.append(
                _issue(
                    "table",
                    record_id,
                    "表头、合并关系、脚注或数据单元格结构不匹配",
                    {key: target.get(key, []) for key in keys},
                    {key: observed.get(key, []) for key in keys} if observed else None,
                )
            )
    return _metric(matched, len(expected)), issues


def _evaluate_translations(
    expected: dict[str, dict[str, Any]],
    actual: dict[str, dict[str, Any]],
) -> tuple[dict[str, int | float | None], list[dict[str, Any]]]:
    total_score = 0.0
    passed = 0
    issues: list[dict[str, Any]] = []
    for record_id, target in expected.items():
        observed = actual.get(record_id)
        reference = _normalized_text(target.get("reference", ""))
        translation = _normalized_text(observed.get("translation", "")) if observed else ""
        score = SequenceMatcher(None, reference, translation).ratio() if reference else 0.0
        total_score += score
        threshold_value = _number(target.get("min_score", 1.0))
        threshold = threshold_value if threshold_value is not None else 1.0
        if observed is not None and score >= threshold:
            passed += 1
        else:
            issues.append(
                _issue(
                    "translation",
                    record_id,
                    f"参考文本相似度 {score:.4f} 低于开发预检阈值 {threshold:.4f}",
                    target.get("reference"),
                    observed.get("translation") if observed else None,
                )
            )
    return {
        "matched": passed,
        "total": len(expected),
        "score": total_score / len(expected) if expected else None,
    }, issues


def evaluate(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    expected_sections = {section: _records_by_id(expected, section) for section in SECTIONS}
    actual_sections = {section: _records_by_id(actual, section) for section in SECTIONS}
    evaluators = {
        "parsing_completeness": ("documents", _evaluate_documents),
        "field_accuracy": ("fields", _evaluate_fields),
        "numeric_tolerance_accuracy": ("numbers", _evaluate_numbers),
        "association_accuracy": ("associations", _evaluate_associations),
        "table_structure_accuracy": ("tables", _evaluate_tables),
        "translation_reference_score": ("translations", _evaluate_translations),
    }
    metrics: dict[str, Any] = {}
    issues: list[dict[str, Any]] = []
    for metric_name, (section, evaluator) in evaluators.items():
        metric, metric_issues = evaluator(
            expected_sections[section],
            actual_sections[section],
        )
        metrics[metric_name] = metric
        issues.extend(metric_issues)
    for section in SECTIONS:
        extras = actual_sections[section].keys() - expected_sections[section].keys()
        issues.extend(
            _issue("unexpected", record_id, f"actual.{section} 中存在未评分记录", None, record)
            for record_id in sorted(extras)
            for record in [actual_sections[section][record_id]]
        )
    return {
        "report_type": "development_precheck",
        "customer_accuracy_claimed": False,
        "notice": "该结果来自所提供 JSON；合成 fixture 仅验证工具，不代表客户真实准确率。",
        "metrics": metrics,
        "issues": issues,
    }


def render_markdown(report: dict[str, Any]) -> str:
    labels = {
        "parsing_completeness": "解析完整率",
        "field_accuracy": "字段准确率",
        "numeric_tolerance_accuracy": "数值容差准确率",
        "association_accuracy": "关联准确率",
        "table_structure_accuracy": "表格结构准确率",
        "translation_reference_score": "翻译参考文本相似度",
    }
    lines = [
        "# 金标准评估问题清单",
        "",
        "> 开发预检结果；不得据此声称客户真实准确率。正式结论须使用客户签字样本与规则。",
        "",
        "## 指标",
        "",
        "| 指标 | 匹配 | 总数 | 分数 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, metric in report["metrics"].items():
        score = metric["score"]
        display = "N/A" if score is None else f"{score:.4f}"
        lines.append(
            f"| {labels.get(name, name)} | {metric['matched']} | {metric['total']} | {display} |"
        )
    lines.extend(
        [
            "",
            "## 问题",
            "",
            "| 类别 | ID | 原因 |",
            "| --- | --- | --- |",
        ]
    )
    if report["issues"]:
        for issue in report["issues"]:
            reason = str(issue["reason"]).replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {issue['category']} | {issue['id']} | {reason} |")
    else:
        lines.append("| - | - | 未发现差异 |")
    return "\n".join(lines) + "\n"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} 顶层必须是对象")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="评估金标准 expected/actual JSON")
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--actual", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    args = parser.parse_args()

    report = evaluate(_read_json(args.expected), _read_json(args.actual))
    args.json_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
    print(f"已输出 {args.json_output} 和 {args.markdown_output}")


if __name__ == "__main__":
    main()
