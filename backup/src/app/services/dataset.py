import hashlib
import json
from collections import defaultdict
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.tables import table
from app.models import DocumentVersion, ProcessingJob
from app.schemas.dataset import (
    DatasetBuildCreate,
    DatasetCellUpdate,
    DatasetFieldCreate,
    DatasetRowCreate,
    DatasetVersionClone,
)
from app.schemas.workflow import TaskAccepted
from app.services.audit import AuditService
from app.services.storage import LocalStorage


class DatasetService:
    def __init__(self, db: Session, storage: LocalStorage) -> None:
        self.db = db
        self.storage = storage

    def create_from_extraction(
        self,
        project_id: UUID,
        payload: DatasetBuildCreate,
        actor_id: UUID | None,
    ) -> TaskAccepted:
        extraction_runs = table(self.db, "extraction_runs")
        extraction = (
            self.db.execute(
                select(extraction_runs).where(
                    extraction_runs.c.id == payload.extraction_run_id,
                    extraction_runs.c.project_id == project_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        if not extraction:
            raise AppError(
                code="extraction_run_not_found", message="抽取任务不存在", status_code=404
            )
        if extraction["status"] != "completed":
            raise AppError(
                code="extraction_not_completed", message="抽取完成后才能生成数据集", status_code=409
            )
        datasets = table(self.db, "datasets")
        versions = table(self.db, "dataset_versions")
        dataset_id = self.db.execute(
            insert(datasets)
            .values(
                project_id=project_id,
                name=payload.name,
                description=payload.description,
                purpose="research",
                status="active",
                settings={},
                created_by=actor_id,
            )
            .returning(datasets.c.id)
        ).scalar_one()
        version_id = self.db.execute(
            insert(versions)
            .values(
                dataset_id=dataset_id,
                version_no=1,
                field_schema_id=extraction["field_schema_id"],
                source_extraction_run_id=payload.extraction_run_id,
                status="draft",
                metadata={"include_review_statuses": payload.include_review_statuses},
                created_by=actor_id,
            )
            .returning(versions.c.id)
        ).scalar_one()
        job = ProcessingJob(
            project_id=project_id,
            job_type="build_dataset",
            status="queued",
            progress_percent=0,
            current_stage="waiting",
            idempotency_key=f"build_dataset:{version_id}",
            requested_config={"dataset_version_id": str(version_id)},
            result_summary={},
            requested_by=actor_id,
        )
        self.db.add(job)
        AuditService(self.db).record(
            project_id=project_id,
            actor_id=actor_id,
            entity_type="dataset",
            entity_id=dataset_id,
            action="create",
            after={"name": payload.name, "version_id": str(version_id)},
        )
        self.db.commit()
        return TaskAccepted(resource_id=version_id, job_id=job.id)

    def _version_context(self, project_id: UUID, version_id: UUID) -> tuple[dict, dict]:
        datasets = table(self.db, "datasets")
        versions = table(self.db, "dataset_versions")
        row = (
            self.db.execute(
                select(datasets, versions)
                .join(versions, versions.c.dataset_id == datasets.c.id)
                .where(
                    versions.c.id == version_id,
                    datasets.c.project_id == project_id,
                    datasets.c.deleted_at.is_(None),
                )
            )
            .mappings()
            .one_or_none()
        )
        if not row:
            raise AppError(
                code="dataset_version_not_found", message="数据集版本不存在", status_code=404
            )
        dataset_data = {column.name: row[column] for column in datasets.c}
        version_data = {column.name: row[column] for column in versions.c}
        return dataset_data, version_data

    def list_datasets(self, project_id: UUID) -> list[dict]:
        datasets = table(self.db, "datasets")
        versions = table(self.db, "dataset_versions")
        latest = (
            select(versions.c.dataset_id, func.max(versions.c.version_no).label("version_no"))
            .group_by(versions.c.dataset_id)
            .subquery()
        )
        rows = (
            self.db.execute(
                select(
                    datasets,
                    versions.c.id.label("latest_version_id"),
                    versions.c.version_no.label("latest_version_no"),
                    versions.c.status.label("latest_version_status"),
                    versions.c.row_count,
                    versions.c.field_count,
                )
                .join(latest, latest.c.dataset_id == datasets.c.id)
                .join(
                    versions,
                    (versions.c.dataset_id == latest.c.dataset_id)
                    & (versions.c.version_no == latest.c.version_no),
                )
                .where(datasets.c.project_id == project_id, datasets.c.deleted_at.is_(None))
                .order_by(datasets.c.created_at.desc())
            )
            .mappings()
            .all()
        )
        return [dict(row) for row in rows]

    def get_version(self, project_id: UUID, version_id: UUID, offset: int, limit: int) -> dict:
        dataset_data, version_data = self._version_context(project_id, version_id)
        fields = table(self.db, "dataset_fields")
        rows = table(self.db, "dataset_rows")
        cells = table(self.db, "dataset_cells")
        field_rows = [
            dict(row)
            for row in self.db.execute(
                select(fields)
                .where(fields.c.dataset_version_id == version_id)
                .order_by(fields.c.position)
            ).mappings()
        ]
        row_rows = [
            dict(row)
            for row in self.db.execute(
                select(rows)
                .where(rows.c.dataset_version_id == version_id, rows.c.is_deleted.is_(False))
                .order_by(rows.c.row_no)
                .offset(offset)
                .limit(limit)
            ).mappings()
        ]
        row_ids = [row["id"] for row in row_rows]
        cell_rows = (
            self.db.execute(select(cells).where(cells.c.row_id.in_(row_ids))).mappings().all()
            if row_ids
            else []
        )
        by_row: dict[UUID, dict[str, dict]] = defaultdict(dict)
        field_key = {field["id"]: field["field_key"] for field in field_rows}
        for cell in cell_rows:
            by_row[cell["row_id"]][field_key[cell["field_id"]]] = dict(cell)
        for row in row_rows:
            row["cells"] = by_row.get(row["id"], {})
        return {
            "dataset": dataset_data,
            "version": version_data,
            "fields": field_rows,
            "rows": row_rows,
            "offset": offset,
            "limit": limit,
        }

    def add_field(
        self, project_id: UUID, version_id: UUID, payload: DatasetFieldCreate, actor_id: UUID | None
    ) -> dict:
        _, version = self._version_context(project_id, version_id)
        if version["status"] != "draft":
            raise AppError(
                code="dataset_immutable", message="只有草稿版本可增加字段", status_code=409
            )
        fields = table(self.db, "dataset_fields")
        position = (
            self.db.scalar(
                select(func.max(fields.c.position)).where(fields.c.dataset_version_id == version_id)
            )
            or -1
        ) + 1
        row = (
            self.db.execute(
                insert(fields)
                .values(
                    dataset_version_id=version_id,
                    field_key=payload.field_key,
                    display_name=payload.display_name,
                    data_type=payload.data_type,
                    semantic_role=payload.semantic_role,
                    unit_id=payload.unit_id,
                    position=position,
                    is_required=payload.is_required,
                    validation_rules={},
                    display_config={},
                    metadata={},
                )
                .returning(fields)
            )
            .mappings()
            .one()
        )
        AuditService(self.db).record(
            project_id=project_id,
            actor_id=actor_id,
            entity_type="dataset_field",
            entity_id=row["id"],
            action="create",
            after=dict(row),
        )
        self.db.commit()
        return dict(row)

    def add_row(
        self, project_id: UUID, version_id: UUID, payload: DatasetRowCreate, actor_id: UUID | None
    ) -> dict:
        _, version = self._version_context(project_id, version_id)
        if version["status"] != "draft":
            raise AppError(
                code="dataset_immutable", message="只有草稿版本可增加行", status_code=409
            )
        rows = table(self.db, "dataset_rows")
        row_no = (
            self.db.scalar(
                select(func.max(rows.c.row_no)).where(rows.c.dataset_version_id == version_id)
            )
            or 0
        ) + 1
        row = (
            self.db.execute(
                insert(rows)
                .values(
                    dataset_version_id=version_id,
                    row_no=row_no,
                    row_key=payload.row_key,
                    source_document_id=payload.source_document_id,
                    source_document_version_id=payload.source_document_version_id,
                    review_status="pending",
                    is_deleted=False,
                    metadata=payload.metadata,
                    created_by=actor_id,
                )
                .returning(rows)
            )
            .mappings()
            .one()
        )
        AuditService(self.db).record(
            project_id=project_id,
            actor_id=actor_id,
            entity_type="dataset_row",
            entity_id=row["id"],
            action="create",
            after=dict(row),
        )
        self.db.commit()
        return dict(row)

    def update_cell(
        self,
        project_id: UUID,
        version_id: UUID,
        row_id: UUID,
        field_id: UUID,
        payload: DatasetCellUpdate,
        actor_id: UUID | None,
    ) -> dict:
        _, version = self._version_context(project_id, version_id)
        if version["status"] != "draft":
            raise AppError(code="dataset_immutable", message="冻结版本不可修改", status_code=409)
        rows = table(self.db, "dataset_rows")
        fields = table(self.db, "dataset_fields")
        cells = table(self.db, "dataset_cells")
        if not self.db.scalar(
            select(rows.c.id).where(rows.c.id == row_id, rows.c.dataset_version_id == version_id)
        ):
            raise AppError(code="dataset_row_not_found", message="数据行不存在", status_code=404)
        if not self.db.scalar(
            select(fields.c.id).where(
                fields.c.id == field_id, fields.c.dataset_version_id == version_id
            )
        ):
            raise AppError(
                code="dataset_field_not_found", message="数据字段不存在", status_code=404
            )
        before = (
            self.db.execute(
                select(cells).where(cells.c.row_id == row_id, cells.c.field_id == field_id)
            )
            .mappings()
            .one_or_none()
        )
        values = payload.model_dump(exclude_unset=True)
        if "value_date" in values and isinstance(values["value_date"], str):
            values["value_date"] = date.fromisoformat(values["value_date"])
        values["is_manually_modified"] = True
        values["modified_by"] = actor_id
        statement = (
            pg_insert(cells)
            .values(row_id=row_id, field_id=field_id, value_source="manual", **values)
            .on_conflict_do_update(index_elements=[cells.c.row_id, cells.c.field_id], set_=values)
            .returning(cells)
        )
        row = self.db.execute(statement).mappings().one()
        AuditService(self.db).record(
            project_id=project_id,
            actor_id=actor_id,
            entity_type="dataset_cell",
            entity_id=row["id"],
            action="update" if before else "create",
            before=dict(before) if before else None,
            after=dict(row),
        )
        self.db.commit()
        return dict(row)

    def delete_row(
        self, project_id: UUID, version_id: UUID, row_id: UUID, actor_id: UUID | None
    ) -> None:
        self._version_context(project_id, version_id)
        rows = table(self.db, "dataset_rows")
        result = self.db.execute(
            update(rows)
            .where(rows.c.id == row_id, rows.c.dataset_version_id == version_id)
            .values(is_deleted=True, review_status="deleted")
        )
        if not getattr(result, "rowcount", 0):
            raise AppError(code="dataset_row_not_found", message="数据行不存在", status_code=404)
        AuditService(self.db).record(
            project_id=project_id,
            actor_id=actor_id,
            entity_type="dataset_row",
            entity_id=row_id,
            action="soft_delete",
        )
        self.db.commit()

    def freeze(self, project_id: UUID, version_id: UUID, actor_id: UUID | None) -> dict:
        _, version = self._version_context(project_id, version_id)
        if version["status"] != "draft":
            raise AppError(
                code="dataset_not_freezable", message="只有草稿版本可冻结", status_code=409
            )
        fields = table(self.db, "dataset_fields")
        rows = table(self.db, "dataset_rows")
        cells = table(self.db, "dataset_cells")
        snapshot = [
            dict(row)
            for row in self.db.execute(
                select(
                    rows.c.row_key,
                    fields.c.field_key,
                    cells.c.raw_value,
                    cells.c.normalized_value,
                    cells.c.ml_value,
                    cells.c.value_text,
                    cells.c.value_number,
                )
                .join(cells, cells.c.row_id == rows.c.id)
                .join(fields, fields.c.id == cells.c.field_id)
                .where(rows.c.dataset_version_id == version_id, rows.c.is_deleted.is_(False))
                .order_by(rows.c.row_no, fields.c.position)
            ).mappings()
        ]
        content_hash = hashlib.sha256(
            json.dumps(snapshot, ensure_ascii=False, default=str, sort_keys=True).encode()
        ).hexdigest()
        versions = table(self.db, "dataset_versions")
        row_count = (
            self.db.scalar(
                select(func.count())
                .select_from(rows)
                .where(rows.c.dataset_version_id == version_id, rows.c.is_deleted.is_(False))
            )
            or 0
        )
        field_count = (
            self.db.scalar(
                select(func.count())
                .select_from(fields)
                .where(fields.c.dataset_version_id == version_id)
            )
            or 0
        )
        updated = (
            self.db.execute(
                update(versions)
                .where(versions.c.id == version_id, versions.c.status == "draft")
                .values(
                    status="frozen",
                    content_sha256=content_hash,
                    row_count=row_count,
                    field_count=field_count,
                    frozen_by=actor_id,
                    frozen_at=func.now(),
                )
                .returning(versions)
            )
            .mappings()
            .one()
        )
        AuditService(self.db).record(
            project_id=project_id,
            actor_id=actor_id,
            entity_type="dataset_version",
            entity_id=version_id,
            action="freeze",
            after={"sha256": content_hash},
        )
        self.db.commit()
        return dict(updated)

    def clone_version(
        self,
        project_id: UUID,
        version_id: UUID,
        payload: DatasetVersionClone,
        actor_id: UUID | None,
    ) -> dict:
        dataset, source = self._version_context(project_id, version_id)
        versions = table(self.db, "dataset_versions")
        fields = table(self.db, "dataset_fields")
        rows = table(self.db, "dataset_rows")
        cells = table(self.db, "dataset_cells")
        evidence = table(self.db, "dataset_cell_evidence")
        next_version = (
            self.db.scalar(
                select(func.max(versions.c.version_no)).where(
                    versions.c.dataset_id == source["dataset_id"]
                )
            )
            or 0
        ) + 1
        new_version_id = self.db.execute(
            insert(versions)
            .values(
                dataset_id=source["dataset_id"],
                version_no=next_version,
                parent_version_id=version_id,
                field_schema_id=source["field_schema_id"],
                source_extraction_run_id=source["source_extraction_run_id"],
                status="draft",
                change_summary=payload.change_summary,
                row_count=source["row_count"],
                field_count=source["field_count"],
                metadata={
                    **(source["metadata"] or {}),
                    "cloned_from_version_id": str(version_id),
                },
                created_by=actor_id,
            )
            .returning(versions.c.id)
        ).scalar_one()
        field_map: dict[UUID, UUID] = {}
        for item in self.db.execute(
            select(fields)
            .where(fields.c.dataset_version_id == version_id)
            .order_by(fields.c.position)
        ).mappings():
            field_map[item["id"]] = self.db.execute(
                insert(fields)
                .values(
                    dataset_version_id=new_version_id,
                    source_field_id=item["source_field_id"],
                    field_key=item["field_key"],
                    display_name=item["display_name"],
                    data_type=item["data_type"],
                    semantic_role=item["semantic_role"],
                    unit_id=item["unit_id"],
                    position=item["position"],
                    is_required=item["is_required"],
                    is_hidden=item["is_hidden"],
                    validation_rules=item["validation_rules"],
                    display_config=item["display_config"],
                    metadata=item["metadata"],
                )
                .returning(fields.c.id)
            ).scalar_one()
        row_map: dict[UUID, UUID] = {}
        for item in self.db.execute(
            select(rows).where(rows.c.dataset_version_id == version_id).order_by(rows.c.row_no)
        ).mappings():
            row_map[item["id"]] = self.db.execute(
                insert(rows)
                .values(
                    dataset_version_id=new_version_id,
                    row_no=item["row_no"],
                    row_key=item["row_key"],
                    source_document_id=item["source_document_id"],
                    source_document_version_id=item["source_document_version_id"],
                    source_sample_key=item["source_sample_key"],
                    review_status=item["review_status"],
                    is_deleted=item["is_deleted"],
                    metadata=item["metadata"],
                    created_by=actor_id,
                )
                .returning(rows.c.id)
            ).scalar_one()
        cell_map: dict[UUID, UUID] = {}
        source_cells = self.db.execute(
            select(cells).where(cells.c.row_id.in_(list(row_map)))
        ).mappings()
        excluded = {"id", "row_id", "field_id", "created_at", "updated_at"}
        for item in source_cells:
            values = {key: value for key, value in item.items() if key not in excluded}
            values.update(row_id=row_map[item["row_id"]], field_id=field_map[item["field_id"]])
            cell_map[item["id"]] = self.db.execute(
                insert(cells).values(**values).returning(cells.c.id)
            ).scalar_one()
        if cell_map:
            excluded_evidence = {"id", "dataset_cell_id", "created_at"}
            for item in self.db.execute(
                select(evidence).where(evidence.c.dataset_cell_id.in_(list(cell_map)))
            ).mappings():
                values = {key: value for key, value in item.items() if key not in excluded_evidence}
                values["dataset_cell_id"] = cell_map[item["dataset_cell_id"]]
                self.db.execute(insert(evidence).values(**values))
        AuditService(self.db).record(
            project_id=project_id,
            actor_id=actor_id,
            entity_type="dataset_version",
            entity_id=new_version_id,
            action="clone",
            before={"version_id": str(version_id), "version_no": source["version_no"]},
            after={"version_id": str(new_version_id), "version_no": next_version},
            reason=payload.change_summary,
        )
        self.db.commit()
        return {
            "dataset_id": dataset["id"],
            "version_id": new_version_id,
            "version_no": next_version,
            "parent_version_id": version_id,
            "status": "draft",
        }

    def build(self, version_id: UUID, progress: Callable[[float, str], None]) -> dict[str, Any]:
        datasets = table(self.db, "datasets")
        versions = table(self.db, "dataset_versions")
        dataset_fields = table(self.db, "dataset_fields")
        dataset_rows = table(self.db, "dataset_rows")
        dataset_cells = table(self.db, "dataset_cells")
        cell_evidence = table(self.db, "dataset_cell_evidence")
        source_fields = table(self.db, "field_definitions")
        records = table(self.db, "extraction_records")
        evidence = table(self.db, "extraction_evidence")
        version = (
            self.db.execute(
                select(versions, datasets.c.project_id)
                .join(datasets, datasets.c.id == versions.c.dataset_id)
                .where(versions.c.id == version_id)
            )
            .mappings()
            .one_or_none()
        )
        if not version:
            raise AppError(
                code="dataset_version_not_found", message="数据集版本不存在", status_code=404
            )
        self.db.execute(delete(dataset_rows).where(dataset_rows.c.dataset_version_id == version_id))
        self.db.execute(
            delete(dataset_fields).where(dataset_fields.c.dataset_version_id == version_id)
        )
        field_rows = [
            dict(row)
            for row in self.db.execute(
                select(source_fields)
                .where(source_fields.c.field_schema_id == version["field_schema_id"])
                .order_by(source_fields.c.position)
            ).mappings()
        ]
        field_map: dict[UUID, UUID] = {}
        for source in field_rows:
            field_id = self.db.execute(
                insert(dataset_fields)
                .values(
                    dataset_version_id=version_id,
                    source_field_id=source["id"],
                    field_key=source["field_key"],
                    display_name=source["display_name"],
                    data_type=source["data_type"],
                    semantic_role=source["semantic_role"],
                    unit_id=source["preferred_unit_id"],
                    position=source["position"],
                    is_required=source["is_required"],
                    validation_rules=source["validation_rules"],
                    display_config=source["display_config"],
                    metadata={},
                )
                .returning(dataset_fields.c.id)
            ).scalar_one()
            field_map[source["id"]] = field_id
        progress(20, "created_fields")

        statuses = (version["metadata"] or {}).get(
            "include_review_statuses", ["pending", "confirmed", "modified"]
        )
        record_rows = [
            dict(row)
            for row in self.db.execute(
                select(records)
                .where(
                    records.c.extraction_run_id == version["source_extraction_run_id"],
                    records.c.review_status.in_(statuses),
                )
                .order_by(records.c.created_at)
            ).mappings()
        ]
        grouped: dict[str, list[dict]] = defaultdict(list)
        for record in record_rows:
            grouped[record["group_key"] or record["sample_key"]].append(record)
        for row_no, (row_key, group_records) in enumerate(grouped.items(), start=1):
            document_version_id = group_records[0]["document_version_id"]
            document_id = self.db.scalar(
                select(DocumentVersion.document_id).where(DocumentVersion.id == document_version_id)
            )
            row_id = self.db.execute(
                insert(dataset_rows)
                .values(
                    dataset_version_id=version_id,
                    row_no=row_no,
                    row_key=row_key,
                    source_document_id=document_id,
                    source_document_version_id=document_version_id,
                    source_sample_key=group_records[0]["sample_key"],
                    review_status="pending",
                    is_deleted=False,
                    metadata={"record_count": len(group_records)},
                )
                .returning(dataset_rows.c.id)
            ).scalar_one()
            used_fields: set[UUID] = set()
            for record in group_records:
                target_field = field_map.get(record["field_definition_id"])
                if not target_field or target_field in used_fields:
                    continue
                used_fields.add(target_field)
                parsed = record["parsed_value"] or {}
                cell_id = self.db.execute(
                    insert(dataset_cells)
                    .values(
                        row_id=row_id,
                        field_id=target_field,
                        source_extraction_record_id=record["id"],
                        raw_value=record["raw_value"],
                        raw_unit_text=record["raw_unit_text"],
                        normalized_value=record["normalized_value"],
                        ml_value=record["ml_value"],
                        value_number=record["numeric_value"],
                        range_min=record["range_min"],
                        range_max=record["range_max"],
                        mean_value=record["mean_value"],
                        standard_deviation=record["standard_deviation"],
                        significance_marker=record["significance_marker"],
                        unit_id=record["normalized_unit_id"],
                        value_source="extracted",
                        review_status=record["review_status"],
                        confidence=record["confidence"],
                        is_missing=record["is_missing"],
                        is_image_estimate=record["is_image_estimate"],
                        is_manually_modified=False,
                        metadata={"parsed_value": parsed},
                    )
                    .returning(dataset_cells.c.id)
                ).scalar_one()
                evidence_rows = (
                    self.db.execute(
                        select(evidence).where(evidence.c.extraction_record_id == record["id"])
                    )
                    .mappings()
                    .all()
                )
                for item in evidence_rows:
                    self.db.execute(
                        insert(cell_evidence).values(
                            dataset_cell_id=cell_id,
                            extraction_evidence_id=item["id"],
                            document_version_id=item["document_version_id"],
                            page_id=item["page_id"],
                            block_id=item["block_id"],
                            table_cell_id=item["table_cell_id"],
                            figure_id=item["figure_id"],
                            evidence_text=item["evidence_text"],
                            bbox=item["bbox"],
                            is_primary=item["is_primary"],
                        )
                    )
            if row_no % 50 == 0:
                progress(20 + 75 * row_no / max(len(grouped), 1), "building_rows")
                self.db.commit()
        self.db.execute(
            update(versions)
            .where(versions.c.id == version_id)
            .values(row_count=len(grouped), field_count=len(field_rows))
        )
        self.db.commit()
        return {
            "dataset_version_id": str(version_id),
            "row_count": len(grouped),
            "field_count": len(field_rows),
        }

    def export_xlsx(self, project_id: UUID, version_id: UUID) -> Path:
        dataset_data, version_data = self._version_context(project_id, version_id)
        content = self.get_version(
            project_id, version_id, 0, max(int(version_data["row_count"] or 0), 1_000_000)
        )
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "dataset_main"
        fields = content["fields"]
        sheet.append([field["display_name"] for field in fields])
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="305496")
        for row in content["rows"]:
            values = []
            for field in fields:
                cell = row["cells"].get(field["field_key"])
                if not cell:
                    values.append("——")
                elif cell["raw_value"] is not None:
                    values.append(cell["raw_value"])
                elif cell["value_number"] is not None:
                    values.append(cell["value_number"])
                else:
                    values.append(cell["value_text"] or "——")
            sheet.append(values)
        trace = workbook.create_sheet("traceability")
        trace.append(["row_key", "field_key", "raw_value", "page_no", "evidence_text"])
        evidence_table = table(self.db, "dataset_cell_evidence")
        cells = table(self.db, "dataset_cells")
        rows_table = table(self.db, "dataset_rows")
        fields_table = table(self.db, "dataset_fields")
        pages = table(self.db, "document_pages")
        trace_rows = self.db.execute(
            select(
                rows_table.c.row_key,
                fields_table.c.field_key,
                cells.c.raw_value,
                pages.c.page_no,
                evidence_table.c.evidence_text,
            )
            .join(cells, cells.c.row_id == rows_table.c.id)
            .join(fields_table, fields_table.c.id == cells.c.field_id)
            .join(evidence_table, evidence_table.c.dataset_cell_id == cells.c.id)
            .join(pages, pages.c.id == evidence_table.c.page_id)
            .where(rows_table.c.dataset_version_id == version_id)
        ).all()
        for row in trace_rows:
            trace.append(list(row))
        output_dir = self.storage.path_for_key(f"exports/{project_id}")
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / f"dataset-{dataset_data['id']}-v{version_data['version_no']}.xlsx"
        workbook.save(output)
        return output
