import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_digest(manifest: dict[str, Any]) -> str:
    payload = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_manifest(root: Path, files: list[Path]) -> dict[str, Any]:
    resolved_root = root.resolve()
    entries: list[dict[str, Any]] = []
    for candidate in sorted(files, key=lambda item: item.as_posix()):
        resolved = (root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        try:
            relative = resolved.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError(f"文件不在金标准目录内: {candidate}") from exc
        if not resolved.is_file():
            raise ValueError(f"文件不存在或不是普通文件: {candidate}")
        entries.append(
            {
                "path": relative.as_posix(),
                "size": resolved.stat().st_size,
                "sha256": sha256_file(resolved),
            }
        )
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "files": entries,
    }
    manifest["manifest_sha256"] = manifest_digest(manifest)
    return manifest


def verify_manifest(manifest: dict[str, Any], root: Path) -> list[str]:
    issues: list[str] = []
    if manifest.get("schema_version") != SCHEMA_VERSION:
        issues.append(f"不支持的 schema_version: {manifest.get('schema_version')!r}")
    recorded_digest = manifest.get("manifest_sha256")
    if not isinstance(recorded_digest, str) or recorded_digest != manifest_digest(manifest):
        issues.append("manifest_sha256 不匹配")
    files = manifest.get("files")
    if not isinstance(files, list):
        return [*issues, "files 必须是数组"]

    resolved_root = root.resolve()
    seen: set[str] = set()
    for index, entry in enumerate(files):
        if not isinstance(entry, dict):
            issues.append(f"files[{index}] 必须是对象")
            continue
        relative = entry.get("path")
        if not isinstance(relative, str) or not relative:
            issues.append(f"files[{index}].path 无效")
            continue
        if relative in seen:
            issues.append(f"重复文件路径: {relative}")
            continue
        seen.add(relative)
        candidate = (resolved_root / relative).resolve()
        try:
            candidate.relative_to(resolved_root)
        except ValueError:
            issues.append(f"文件路径越界: {relative}")
            continue
        if not candidate.is_file():
            issues.append(f"文件不存在: {relative}")
            continue
        expected_size = entry.get("size")
        if not isinstance(expected_size, int) or candidate.stat().st_size != expected_size:
            issues.append(f"文件大小不匹配: {relative}")
        expected_sha = entry.get("sha256")
        if not isinstance(expected_sha, str) or sha256_file(candidate) != expected_sha.lower():
            issues.append(f"SHA-256 不匹配: {relative}")
    return issues


def load_and_verify_manifest(path: Path, root: Path | None = None) -> tuple[dict[str, Any], list[str]]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("manifest 顶层必须是对象")
    return manifest, verify_manifest(manifest, root or path.parent)


def main() -> None:
    parser = argparse.ArgumentParser(description="生成或校验客户金标准 SHA-256 manifest")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create", help="生成 manifest")
    create.add_argument("root", type=Path)
    create.add_argument("files", nargs="+", type=Path)
    create.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify", help="校验 manifest 和文件")
    verify.add_argument("manifest", type=Path)
    verify.add_argument("--root", type=Path)
    args = parser.parse_args()

    if args.command == "create":
        manifest = build_manifest(args.root, args.files)
        args.output.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"已生成 {args.output}，包含 {len(manifest['files'])} 个文件")
        return

    _, issues = load_and_verify_manifest(args.manifest, args.root)
    if issues:
        for issue in issues:
            print(f"FAIL: {issue}")
        raise SystemExit(1)
    print("manifest 与全部文件 SHA-256 校验通过")


if __name__ == "__main__":
    main()
