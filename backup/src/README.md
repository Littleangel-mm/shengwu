# Research Platform API

FastAPI backend for the generic research document extraction and machine learning platform.

## Run

1. Copy `.env.example` to `.env` and configure the database connection.
2. Install dependencies: `python -m pip install -e ".[dev]"`
3. Start the API: `python -m app`
4. Start the persistent worker in another terminal: `python -m app.worker`
5. Open API docs: `http://127.0.0.1:8000/docs`

The database schema is managed by the SQL migrations in the workspace `sql` directory. The
application does not call `create_all()` and will not create or drop production tables.

## Database migrations

Create a new empty database with the current schema:

```powershell
python -m alembic upgrade head
```

For an existing database that was created from `migrations/sql/001_initial_schema.sql`, record the
baseline without replaying the schema:

```powershell
python -m alembic stamp 20260719_001
python -m alembic current
```

Do not run the initial upgrade against a populated database that has not first been inspected. New
schema changes must be delivered as additional Alembic revisions.

## Implemented workflow

`project -> upload -> parse -> search -> term review -> field schema -> extraction -> dataset -> freeze -> train -> predict/optimize -> Excel/Word export`

Long-running work is persisted in `processing_jobs`. The API can execute a job immediately through
the development endpoint, while normal deployments should keep `python -m app.worker` running.

Supported document parsers:

- PDF: embedded text, page coordinates, detected tables and embedded images
- DOCX: paragraphs and tables
- TXT/Markdown: paragraph blocks
- XLSX: sheets, cells and table text
- ZIP: safe archive validation plus automatic import of supported child documents

Scanned PDF pages attempt OCR when the local OCR engine is available. Otherwise the document is
marked `partial` with `requires_ocr=true`; the platform never fabricates missing text.

## PaddleOCR setup

PaddleOCR runs in a separate Python 3.12 environment so its native dependencies do not conflict
with the FastAPI environment. From this directory:

```powershell
uv venv .venv-ocr --python 3.12
uv pip install --python .venv-ocr\Scripts\python.exe -r ocr-requirements.txt
```

The configured CPU models are `PP-OCRv5_mobile_det` and `PP-OCRv5_mobile_rec`. Their relative
directories are configured through `OCR_DETECTION_MODEL_DIR` and `OCR_RECOGNITION_MODEL_DIR`.
The worker renders all image-only pages, sends them to one PaddleOCR process as a batch, then stores
recognized text, per-page confidence and PDF coordinates. Check installation status at
`GET /api/v1/health/ocr`.

Windows CPU execution deliberately sets `FLAGS_use_mkldnn=0` and `FLAGS_enable_pir_api=0` to avoid
the Paddle 3.3 oneDNN/PIR incompatibility. This is slower than GPU inference but stable.

## Security and machine learning

- All project-scoped APIs require a valid access token and enforce project or organization membership.
- Production must set a persistent `APP_SECRET` and set `ALLOW_ACTOR_HEADER=false`.
- Training supports mixed numeric/categorical inputs, configurable imputers and scalers, grouped train/test splits, grouped cross-validation and bounded parameter search.
- Regression models: Ridge, PLS, SVR, Random Forest, Gradient Boosting and XGBoost.
- Classification models: Logistic Regression, SVC, Random Forest, Gradient Boosting and XGBoost.
- Test metrics, cross-validation metrics, permutation importance and SHAP summaries are persisted with each model. A completed model can be selected manually through the API.

## Backup and restore

Backups contain the schema revision, checksummed table exports and, by default, stored files:

```powershell
python scripts/backup.py
python scripts/backup.py --output backups/manual
```

Restore into an empty target database. `--replace` is required when deliberately replacing data in
an initialized target:

```powershell
python scripts/restore.py backups/manual
python scripts/restore.py backups/manual --replace
```

Always test restore with a separate database and storage directory before a production recovery.

## Acceptance checks

Run local static checks and unit tests:

```powershell
python -m ruff check app tests scripts migrations
python -m mypy app scripts
python -m pytest
```

The coverage workflow creates a temporary PostgreSQL database, applies all migrations, runs the
integration workflow and enforces the configured 70% branch-aware coverage threshold. It removes
the temporary database and storage afterward:

```powershell
python scripts/coverage_acceptance.py
```

Scan project content for credentials and absolute workspace paths, then audit resolved Python
dependencies:

```powershell
python scripts/security_check.py
```

After starting the API, run the concurrent readiness acceptance check:

```powershell
python scripts/load_test.py --requests 200 --concurrency 20 --p95-ms 800
```

Customer acceptance accuracy is separate from code coverage. It requires a signed representative
gold-standard document set with expected extraction values, tolerances and scoring rules. Final UAT
also requires customer execution and sign-off; neither result should be claimed from synthetic test
fixtures alone.

Delivery templates are available in `docs/GOLD_STANDARD_SPEC.md` and
`docs/UAT_ACCEPTANCE_REPORT.md`.

## External services and extraction limits

English translation requires `DEEPSEEK_API_KEY`. PaddleOCR is local and does not require a paid API.
The parser extracts values printed directly in figures and preserves their evidence coordinates; it
does not infer unprinted values from trend lines. Dedicated chart digitization can be added as a
later module when that accuracy requirement and its gold-standard samples are available.
