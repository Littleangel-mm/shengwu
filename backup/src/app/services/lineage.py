from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.tables import table


class LineageService:
    """聚合一份报告从原始文件到最终产物的完整来源链（run 级 lineage）。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def _row(self, name: str, key_column: str, value: UUID | None) -> dict[str, Any] | None:
        if value is None:
            return None
        tbl = table(self.db, name)
        row = (
            self.db.execute(select(tbl).where(getattr(tbl.c, key_column) == value))
            .mappings()
            .one_or_none()
        )
        return dict(row) if row else None

    def report_lineage(self, project_id: UUID, report_id: UUID) -> dict[str, Any]:
        reports = table(self.db, "reports")
        report = (
            self.db.execute(
                select(reports).where(
                    reports.c.id == report_id, reports.c.project_id == project_id
                )
            )
            .mappings()
            .one_or_none()
        )
        if not report:
            raise AppError(code="report_not_found", message="报告不存在", status_code=404)

        version = self._row("dataset_versions", "id", report["dataset_version_id"])
        dataset = self._row("datasets", "id", version["dataset_id"]) if version else None
        extraction_run = (
            self._row("extraction_runs", "id", version["source_extraction_run_id"])
            if version
            else None
        )
        field_schema = (
            self._row("field_schemas", "id", version.get("field_schema_id")) if version else None
        )
        search_run_id = None
        if extraction_run:
            search_run_id = extraction_run.get("search_run_id")
        if not search_run_id and field_schema:
            search_run_id = field_schema.get("source_search_run_id")
        search_run = self._row("search_runs", "id", search_run_id)

        ml_run = self._row("ml_runs", "id", report["ml_run_id"])
        ml_models: list[dict[str, Any]] = []
        if ml_run:
            models_tbl = table(self.db, "ml_models")
            ml_models = [
                dict(row)
                for row in self.db.execute(
                    select(
                        models_tbl.c.id,
                        models_tbl.c.display_name,
                        models_tbl.c.algorithm_code,
                        models_tbl.c.status,
                        models_tbl.c.is_selected,
                        models_tbl.c.artifact_sha256,
                    )
                    .where(models_tbl.c.ml_run_id == ml_run["id"])
                    .order_by(models_tbl.c.model_no)
                )
                .mappings()
                .all()
            ]

        optimization_run = self._row("optimization_runs", "id", report["optimization_run_id"])

        source_files: list[dict[str, Any]] = []
        source_document_count = 0
        if version:
            rows_tbl = table(self.db, "dataset_rows")
            documents_tbl = table(self.db, "documents")
            document_versions = table(self.db, "document_versions")
            stored_files = table(self.db, "stored_files")
            source_document_count = (
                self.db.scalar(
                    select(func.count(func.distinct(rows_tbl.c.source_document_id))).where(
                        rows_tbl.c.dataset_version_id == version["id"],
                        rows_tbl.c.source_document_id.is_not(None),
                    )
                )
                or 0
            )
            file_rows = self.db.execute(
                select(
                    stored_files.c.original_name,
                    stored_files.c.extension,
                    stored_files.c.byte_size,
                    stored_files.c.sha256,
                    documents_tbl.c.title,
                )
                .select_from(rows_tbl)
                .join(
                    document_versions,
                    document_versions.c.id == rows_tbl.c.source_document_version_id,
                )
                .join(stored_files, stored_files.c.id == document_versions.c.source_file_id)
                .join(documents_tbl, documents_tbl.c.id == rows_tbl.c.source_document_id)
                .where(rows_tbl.c.dataset_version_id == version["id"])
                .distinct()
                .limit(200)
            ).all()
            source_files = [
                {
                    "title": row.title,
                    "original_name": row.original_name,
                    "extension": row.extension,
                    "byte_size": row.byte_size,
                    "sha256": row.sha256,
                }
                for row in file_rows
            ]

        hash_chain: list[dict[str, Any]] = []
        input_hashes = sorted({item["sha256"] for item in source_files if item["sha256"]})
        if input_hashes:
            hash_chain.append({"stage": "原始文件", "sha256": input_hashes})
        if version and version.get("content_sha256"):
            hash_chain.append({"stage": "冻结数据集", "sha256": version["content_sha256"]})
        model_hashes = sorted({m["artifact_sha256"] for m in ml_models if m.get("artifact_sha256")})
        if model_hashes:
            hash_chain.append({"stage": "模型 artifact", "sha256": model_hashes})
        if report.get("content_sha256"):
            hash_chain.append({"stage": "研究报告", "sha256": report["content_sha256"]})

        def _slim(row: dict[str, Any] | None, keys: tuple[str, ...]) -> dict[str, Any] | None:
            if not row:
                return None
            return {key: row.get(key) for key in keys}

        return {
            "report": _slim(
                dict(report), ("id", "title", "status", "version_no", "content_sha256")
            ),
            "search_run": _slim(search_run, ("id", "name", "status")),
            "field_schema": _slim(field_schema, ("id", "name", "status", "version_no")),
            "extraction_run": _slim(
                extraction_run, ("id", "name", "status", "extractor_name", "extractor_version")
            ),
            "dataset": _slim(dataset, ("id", "name")),
            "dataset_version": _slim(
                version,
                ("id", "version_no", "status", "row_count", "field_count", "content_sha256"),
            ),
            "ml_run": _slim(ml_run, ("id", "name", "status", "random_seed")),
            "ml_models": ml_models,
            "optimization_run": _slim(optimization_run, ("id", "name", "status", "method")),
            "source_document_count": source_document_count,
            "source_files": source_files,
            "hash_chain": hash_chain,
        }
