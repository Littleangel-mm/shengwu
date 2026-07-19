import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any, cast
from zipfile import ZipFile

from app.core.config import get_settings
from app.db.session import engine


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore a backup into an empty target database")
    parser.add_argument("backup", type=Path)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((args.backup / "manifest.json").read_text(encoding="utf-8"))
    for item in manifest["tables"]:
        source = args.backup / "tables" / f"{item['name']}.tsv"
        if sha256(source) != item["sha256"]:
            raise RuntimeError(f"Backup checksum mismatch: {item['name']}")
    settings = get_settings()
    with engine.raw_connection() as connection:
        dbapi_connection = cast(Any, connection)
        dbapi_connection.autocommit = True
        cursor = connection.cursor()
        cursor.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' "
            "AND table_type='BASE TABLE'"
        )
        count_row = cursor.fetchone()
        table_count = count_row[0] if count_row else 0
        initialized_schema = table_count == 0
        if initialized_schema:
            schema = (args.backup / "schema.sql").read_text(encoding="utf-8")
            cursor.execute(schema)
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS alembic_version "
                "(version_num varchar(32) NOT NULL PRIMARY KEY)"
            )
            if manifest.get("alembic_revision"):
                cursor.execute(
                    "INSERT INTO alembic_version(version_num) VALUES (%s) "
                    "ON CONFLICT (version_num) DO NOTHING",
                    (manifest["alembic_revision"],),
                )
        elif not args.replace:
            raise RuntimeError("Target database is not empty; use --replace explicitly")
        cursor.execute("SET session_replication_role = replica")
        try:
            if args.replace or initialized_schema:
                names = ",".join(f'public."{item["name"]}"' for item in manifest["tables"])
                if names:
                    cursor.execute(f"TRUNCATE {names} CASCADE")
            for item in manifest["tables"]:
                source = args.backup / "tables" / f"{item['name']}.tsv"
                with source.open("r", encoding="utf-8", newline="") as content:
                    reader = csv.reader(content, delimiter="\t")
                    columns = next(reader)
                    quoted = ",".join(f'"{column}"' for column in columns)
                    cursor.copy_expert(
                        f'COPY public."{item["name"]}" ({quoted}) FROM STDIN '
                        "WITH (FORMAT CSV, DELIMITER E'\\t', NULL '\\N', QUOTE E'\\b')",
                        content,
                    )
            cursor.execute(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND column_default LIKE 'nextval(%'"
            )
            for table_name, column_name in cursor.fetchall():
                cursor.execute(
                    "SELECT setval(pg_get_serial_sequence(%s,%s), "
                    "GREATEST(COALESCE((SELECT max("
                    + f'"{column_name}"'
                    + ') FROM public."'
                    + table_name
                    + '"), 1), 1), true)',
                    (f"public.{table_name}", column_name),
                )
        finally:
            cursor.execute("SET session_replication_role = origin")
    file_manifest = manifest.get("files")
    if file_manifest:
        archive = args.backup / file_manifest["name"]
        if sha256(archive) != file_manifest["sha256"]:
            raise RuntimeError("Storage archive checksum mismatch")
        settings.storage_root.mkdir(parents=True, exist_ok=True)
        with ZipFile(archive) as source:
            for member in source.infolist():
                target = (settings.storage_root / member.filename).resolve()
                root = settings.storage_root.resolve()
                if root != target and root not in target.parents:
                    raise RuntimeError("Unsafe path in storage archive")
            source.extractall(settings.storage_root)


if __name__ == "__main__":
    main()
