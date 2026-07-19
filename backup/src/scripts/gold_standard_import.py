import argparse
import json
from pathlib import Path
from typing import Any

from scripts.gold_standard_manifest import load_and_verify_manifest

SECTIONS = ("documents", "fields", "numbers", "associations", "tables", "translations")
EXPECTED_KEYS = {
    "documents": set(),
    "fields": {"value"},
    "numbers": {"value", "unit"},
    "associations": {"treatment_group", "timepoint", "condition"},
    "tables": {"headers", "merged_cells", "footnotes", "cells"},
    "translations": {"reference"},
}
ACTUAL_KEYS = {
    "documents": {"parsed", "evidence_locatable"},
    "fields": {"value"},
    "numbers": {"value", "unit"},
    "associations": {"treatment_group", "timepoint", "condition"},
    "tables": {"headers", "merged_cells", "footnotes", "cells"},
    "translations": {"translation"},
}


def validate_payload(payload: Any, label: str) -> list[str]:
    if not isinstance(payload, dict):
        return [f"{label} 顶层必须是对象"]
    issues: list[str] = []
    for section in SECTIONS:
        records = payload.get(section, [])
        if not isinstance(records, list):
            issues.append(f"{label}.{section} 必须是数组")
            continue
        seen: set[str] = set()
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                issues.append(f"{label}.{section}[{index}] 必须是对象")
                continue
            record_id = record.get("id")
            if not isinstance(record_id, str) or not record_id.strip():
                issues.append(f"{label}.{section}[{index}].id 必须是非空字符串")
            elif record_id in seen:
                issues.append(f"{label}.{section} 存在重复 id: {record_id}")
            else:
                seen.add(record_id)
            required = (EXPECTED_KEYS if label == "expected" else ACTUAL_KEYS)[section]
            missing = sorted(required - record.keys())
            if missing:
                issues.append(
                    f"{label}.{section}[{index}] 缺少必填字段: {', '.join(missing)}"
                )
    return issues


def build_import_bundle(
    manifest: dict[str, Any],
    expected: dict[str, Any],
    actual: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "source_manifest_sha256": manifest["manifest_sha256"],
        "notice": "开发合成数据仅验证评估流程，不代表客户真实准确率。",
        "expected": expected,
        "actual": actual,
    }


def read_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} 顶层必须是对象")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="校验并导入金标准 expected/actual JSON")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--actual", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest, issues = load_and_verify_manifest(args.manifest)
    expected = read_json_object(args.expected)
    actual = read_json_object(args.actual)
    issues.extend(validate_payload(expected, "expected"))
    issues.extend(validate_payload(actual, "actual"))
    manifest_paths = {
        entry.get("path")
        for entry in manifest.get("files", [])
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }
    for source in (args.expected, args.actual):
        try:
            relative = source.resolve().relative_to(args.manifest.parent.resolve()).as_posix()
        except ValueError:
            issues.append(f"输入文件不在 manifest 根目录内: {source}")
            continue
        if relative not in manifest_paths:
            issues.append(f"输入文件未登记在 manifest: {relative}")

    if issues:
        for issue in issues:
            print(f"FAIL: {issue}")
        raise SystemExit(1)
    bundle = build_import_bundle(manifest, expected, actual)
    args.output.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已校验并导入到 {args.output}")


if __name__ == "__main__":
    main()
