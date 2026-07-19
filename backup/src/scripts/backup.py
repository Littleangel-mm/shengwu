import argparse
import csv
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from app.core.config import get_settings
from app.db.session import engine


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a portable database and file backup")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--skip-files", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    destination = args.output or Path("backups") / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination.mkdir(parents=True, exist_ok=False)
    schema_source = Path("migrations/sql/001_initial_schema.sql")
    shutil.copy2(schema_source, destination / "schema.sql")
    tables_dir = destination / "tables"
    tables_dir.mkdir()
    manifest: dict[str, Any] = {
        "format": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "database": settings.db_name,
        "tables": [],
        "files": None,
    }
    with engine.raw_connection() as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT to_regclass('public.alembic_version')")
        regclass_row = cursor.fetchone()
        if regclass_row and regclass_row[0]:
            cursor.execute("SELECT version_num FROM alembic_version")
            revision_row = cursor.fetchone()
            manifest["alembic_revision"] = revision_row[0] if revision_row else None
        cursor.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' "
            "AND tablename <> 'alembic_version' ORDER BY tablename"
        )
        for (table_name,) in cursor.fetchall():
            cursor.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=%s "
                "AND is_generated='NEVER' ORDER BY ordinal_position",
                (table_name,),
            )
            columns = [row[0] for row in cursor.fetchall()]
            output = tables_dir / f"{table_name}.tsv"
            with output.open("w", encoding="utf-8", newline="") as target:
                writer = csv.writer(target, delimiter="\t", lineterminator="\n")
                writer.writerow(columns)
                quoted_columns = ",".join(f'"{column}"' for column in columns)
                cursor.copy_expert(
                    f'COPY public."{table_name}" ({quoted_columns}) TO STDOUT '
                    "WITH (FORMAT CSV, DELIMITER E'\\t', NULL '\\N', QUOTE E'\\b')",
                    target,
                )
            manifest["tables"].append(
                {"name": table_name, "columns": columns, "sha256": sha256(output)}
            )
    if not args.skip_files and settings.storage_root.exists():
        archive = destination / "storage.zip"
        with ZipFile(archive, "w", ZIP_DEFLATED, allowZip64=True) as output:
            for path in settings.storage_root.rglob("*"):
                if path.is_file():
                    output.write(path, path.relative_to(settings.storage_root).as_posix())
        manifest["files"] = {"name": archive.name, "sha256": sha256(archive)}
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(destination)


if __name__ == "__main__":
    main()
