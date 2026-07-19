import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import psycopg2


def main() -> None:
    required = ["DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise SystemExit(f"Missing test database settings: {', '.join(missing)}")
    database = "rp_coverage_" + uuid4().hex[:10]
    storage = Path("data") / database
    environment = os.environ.copy()
    environment.update(
        DB_NAME=database,
        STORAGE_ROOT=str(storage),
        APP_SECRET=secrets.token_urlsafe(48),
        ALLOW_ACTOR_HEADER="false",
        RUN_INTEGRATION_TESTS="1",
    )
    admin = psycopg2.connect(
        host=environment["DB_HOST"],
        port=environment["DB_PORT"],
        user=environment["DB_USER"],
        password=environment["DB_PASSWORD"],
        dbname="postgres",
    )
    admin.autocommit = True
    try:
        with admin.cursor() as cursor:
            cursor.execute(f'CREATE DATABASE "{database}"')
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            env=environment,
            check=True,
        )
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "--cov=app",
                "--cov-report=term-missing",
            ],
            env=environment,
            check=False,
        )
        raise SystemExit(result.returncode)
    finally:
        with admin.cursor() as cursor:
            cursor.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s",
                (database,),
            )
            cursor.execute(f'DROP DATABASE IF EXISTS "{database}"')
        admin.close()
        shutil.rmtree(storage, ignore_errors=True)


if __name__ == "__main__":
    main()
