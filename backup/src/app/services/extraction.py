import re
from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import delete, exists, func, insert, select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.tables import table
from app.models import Document, DocumentVersion, ProcessingJob
from app.schemas.workflow import ExtractionCreate, ExtractionRecordReview, TaskAccepted

NUMBER = r"[-+]?\d+(?:\.\d+)?"
VALUE_PATTERN = (
    rf"(?P<value>{NUMBER}(?:\s*(?:±|\+/-)\s*{NUMBER})?|{NUMBER}\s*(?:~|～|—|–|-)\s*{NUMBER})"
)
UNIT_PATTERN = r"(?P<unit>%|℃|°C|K|d|h|min|s|mg/L|g/L|mg/g|g/kg|μg/L|mol/L|ppm|pH)?"


def first_not_none(*values: Any) -> Any:
    return next((value for value in values if value is not None), None)


def parse_numeric(raw: str) -> dict[str, Any]:
    values = [float(item) for item in re.findall(NUMBER, raw)]
    if "±" in raw or "+/-" in raw:
        return {"type": "mean_sd", "mean": values[0], "sd": values[1] if len(values) > 1 else None}
    if any(mark in raw for mark in ("~", "～", "—", "–")) or ("-" in raw[1:] and len(values) > 1):
        return {"type": "range", "min": min(values), "max": max(values), "mid": sum(values[:2]) / 2}
    return {"type": "number", "value": values[0] if values else None}


class ExtractionService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self, project_id: UUID, payload: ExtractionCreate, actor_id: UUID | None
    ) -> TaskAccepted:
        schemas = table(self.db, "field_schemas")
        schema_row = (
            self.db.execute(
                select(schemas).where(
                    schemas.c.id == payload.field_schema_id, schemas.c.project_id == project_id
                )
            )
            .mappings()
            .one_or_none()
        )
        if not schema_row:
            raise AppError(code="field_schema_not_found", message="字段方案不存在", status_code=404)
        if schema_row["status"] != "frozen":
            raise AppError(
                code="field_schema_not_frozen", message="字段方案冻结后才能抽取", status_code=409
            )
        if payload.search_run_id is not None:
            search_runs = table(self.db, "search_runs")
            if not self.db.scalar(
                select(search_runs.c.id).where(
                    search_runs.c.id == payload.search_run_id,
                    search_runs.c.project_id == project_id,
                )
            ):
                raise AppError(
                    code="search_run_not_found", message="检索任务不存在", status_code=404
                )
        runs = table(self.db, "extraction_runs")
        run_id = self.db.execute(
            insert(runs)
            .values(
                project_id=project_id,
                field_schema_id=payload.field_schema_id,
                search_run_id=payload.search_run_id,
                name=payload.name,
                status="queued",
                configuration=payload.configuration,
                extractor_name="rule_evidence_extractor",
                extractor_version="1.0.0",
                created_by=actor_id,
            )
            .returning(runs.c.id)
        ).scalar_one()
        job = ProcessingJob(
            project_id=project_id,
            job_type="run_extraction",
            status="queued",
            progress_percent=0,
            current_stage="waiting",
            idempotency_key=f"run_extraction:{run_id}",
            requested_config={"extraction_run_id": str(run_id)},
            result_summary={},
            requested_by=actor_id,
        )
        self.db.add(job)
        self.db.commit()
        return TaskAccepted(resource_id=run_id, job_id=job.id)

    def list_runs(self, project_id: UUID) -> list[dict]:
        runs = table(self.db, "extraction_runs")
        return [
            dict(row)
            for row in self.db.execute(
                select(runs)
                .where(runs.c.project_id == project_id)
                .order_by(runs.c.created_at.desc())
            ).mappings()
        ]

    def list_records(
        self,
        project_id: UUID,
        run_id: UUID,
        offset: int,
        limit: int,
        field_definition_id: UUID | None = None,
        document_version_id: UUID | None = None,
        review_status: str | None = None,
    ) -> tuple[list[dict], int]:
        runs = table(self.db, "extraction_runs")
        records = table(self.db, "extraction_records")
        fields = table(self.db, "field_definitions")
        evidence = table(self.db, "extraction_evidence")
        pages = table(self.db, "document_pages")
        if not self.db.scalar(
            select(runs.c.id).where(runs.c.id == run_id, runs.c.project_id == project_id)
        ):
            raise AppError(
                code="extraction_run_not_found", message="抽取任务不存在", status_code=404
            )
        filters = [records.c.extraction_run_id == run_id]
        if field_definition_id is not None:
            filters.append(records.c.field_definition_id == field_definition_id)
        if document_version_id is not None:
            filters.append(records.c.document_version_id == document_version_id)
        if review_status is not None:
            filters.append(records.c.review_status == review_status)
        total = (
            self.db.scalar(
                select(func.count()).select_from(records).where(*filters)
            )
            or 0
        )
        rows = (
            self.db.execute(
                select(
                    records,
                    fields.c.display_name.label("field_display_name"),
                    fields.c.field_key.label("field_key"),
                    Document.id.label("document_id"),
                    Document.title.label("document_title"),
                    pages.c.page_no.label("page_no"),
                    evidence.c.bbox.label("bbox"),
                    evidence.c.evidence_text.label("evidence_text"),
                )
                .join(fields, fields.c.id == records.c.field_definition_id)
                .join(DocumentVersion, DocumentVersion.id == records.c.document_version_id)
                .join(Document, Document.id == DocumentVersion.document_id)
                .outerjoin(
                    evidence,
                    (evidence.c.extraction_record_id == records.c.id)
                    & evidence.c.is_primary.is_(True),
                )
                .outerjoin(pages, pages.c.id == evidence.c.page_id)
                .where(*filters)
                .order_by(records.c.created_at)
                .offset(offset)
                .limit(limit)
            )
            .mappings()
            .all()
        )
        return [dict(row) for row in rows], total

    def get_summary(self, project_id: UUID, run_id: UUID) -> dict[str, Any]:
        runs = table(self.db, "extraction_runs")
        records = table(self.db, "extraction_records")
        run = (
            self.db.execute(
                select(runs).where(runs.c.id == run_id, runs.c.project_id == project_id)
            )
            .mappings()
            .one_or_none()
        )
        if not run:
            raise AppError(
                code="extraction_run_not_found", message="抽取任务不存在", status_code=404
            )
        counts = {
            status: 0
            for status in ("pending", "confirmed", "modified", "doubtful", "excluded")
        }
        counts.update(
            {
                row.review_status: int(row.record_count)
                for row in self.db.execute(
                    select(
                        records.c.review_status,
                        func.count().label("record_count"),
                    )
                    .where(records.c.extraction_run_id == run_id)
                    .group_by(records.c.review_status)
                )
            }
        )
        total_records = sum(counts.values())
        field_count, document_count = self.db.execute(
            select(
                func.count(func.distinct(records.c.field_definition_id)),
                func.count(func.distinct(records.c.document_version_id)),
            ).where(records.c.extraction_run_id == run_id)
        ).one()
        return {
            "extraction_run_id": run_id,
            "status": run["status"],
            "total_records": total_records,
            "field_count": field_count or 0,
            "document_count": document_count or 0,
            "review_status_counts": counts,
        }

    def review_record(
        self,
        project_id: UUID,
        run_id: UUID,
        record_id: UUID,
        payload: ExtractionRecordReview,
        actor_id: UUID | None,
    ) -> dict[str, Any]:
        runs = table(self.db, "extraction_runs")
        records = table(self.db, "extraction_records")
        if not self.db.scalar(
            select(records.c.id)
            .join(runs, runs.c.id == records.c.extraction_run_id)
            .where(
                records.c.id == record_id,
                records.c.extraction_run_id == run_id,
                runs.c.project_id == project_id,
            )
        ):
            raise AppError(
                code="extraction_record_not_found", message="抽取记录不存在", status_code=404
            )
        values: dict[str, Any] = {
            "review_status": payload.review_status,
            "reviewed_by": actor_id,
            "reviewed_at": func.now(),
            "updated_at": func.now(),
        }
        for field_name in ("normalized_value", "ml_value", "notes"):
            if field_name in payload.model_fields_set:
                values[field_name] = getattr(payload, field_name)
        row = (
            self.db.execute(
                update(records)
                .where(records.c.id == record_id)
                .values(**values)
                .returning(records)
            )
            .mappings()
            .one()
        )
        self.db.commit()
        return dict(row)

    @staticmethod
    def _dimension_keys(text_value: str, fallback: str) -> tuple[str, str | None]:
        dimensions = ExtractionService._dimension_metadata(text_value)
        treatment_key = dimensions["treatment"] or "unspecified"
        timepoint_key = dimensions["timepoint"]
        return (
            f"{fallback}:treatment={treatment_key}:time={timepoint_key or 'unspecified'}",
            timepoint_key,
        )

    @staticmethod
    def _dimension_metadata(text_value: str) -> dict[str, Any]:
        treatment = re.search(
            r"(?:处理组|处理|组别|样品|group|treatment|sample)\s*[:：]?\s*([A-Za-z0-9_\-\u4e00-\u9fff]{1,30})",
            text_value,
            re.I,
        )
        timepoint = re.search(r"(\d+(?:\.\d+)?)\s*(h|d|min|小时|天|分钟)", text_value, re.I)
        timepoint_key = f"{timepoint.group(1)}{timepoint.group(2)}" if timepoint else None
        conditions: dict[str, str] = {}
        condition_patterns = {
            "temperature": r"(\d+(?:\.\d+)?)\s*(?:℃|°C)",
            "ph": r"\bpH\s*[:=]?\s*(\d+(?:\.\d+)?)",
            "agitation": r"(\d+(?:\.\d+)?)\s*(?:rpm|r/min)",
        }
        for key, pattern in condition_patterns.items():
            match = re.search(pattern, text_value, re.I)
            if match:
                conditions[key] = match.group(0)
        return {
            "treatment": treatment.group(1) if treatment else None,
            "timepoint": timepoint_key,
            "experimental_conditions": conditions,
        }

    def execute(self, run_id: UUID, progress: Callable[[float, str], None]) -> dict[str, Any]:
        runs = table(self.db, "extraction_runs")
        fields = table(self.db, "field_definitions")
        terms = table(self.db, "terms")
        aliases = table(self.db, "term_aliases")
        blocks = table(self.db, "document_blocks")
        pages = table(self.db, "document_pages")
        document_tables = table(self.db, "document_tables")
        table_cells = table(self.db, "document_table_cells")
        figures = table(self.db, "document_figures")
        records = table(self.db, "extraction_records")
        evidence = table(self.db, "extraction_evidence")
        search_results = table(self.db, "search_results")
        run = self.db.execute(select(runs).where(runs.c.id == run_id)).mappings().one_or_none()
        if not run:
            raise AppError(
                code="extraction_run_not_found", message="抽取任务不存在", status_code=404
            )
        field_rows = [
            dict(row)
            for row in self.db.execute(
                select(fields)
                .where(fields.c.field_schema_id == run["field_schema_id"])
                .order_by(fields.c.position)
            ).mappings()
        ]
        if not field_rows:
            raise AppError(code="field_schema_empty", message="字段方案没有字段", status_code=422)
        self.db.execute(delete(records).where(records.c.extraction_run_id == run_id))
        self.db.execute(update(runs).where(runs.c.id == run_id).values(status="running"))
        self.db.commit()

        block_query = (
            select(
                blocks.c.id.label("block_id"),
                blocks.c.document_version_id,
                blocks.c.page_id,
                blocks.c.content_text,
                blocks.c.bbox,
                blocks.c.sequence_no,
                pages.c.page_no,
            )
            .join(pages, pages.c.id == blocks.c.page_id)
            .join(DocumentVersion, DocumentVersion.id == blocks.c.document_version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(Document.project_id == run["project_id"], Document.deleted_at.is_(None))
        )
        if run["search_run_id"] is not None:
            block_query = block_query.where(
                exists(
                    select(1).where(
                        search_results.c.search_run_id == run["search_run_id"],
                        search_results.c.is_included.is_(True),
                        search_results.c.block_id == blocks.c.id,
                    )
                )
            )
        block_rows = (
            self.db.execute(
                block_query.order_by(
                    blocks.c.document_version_id, pages.c.page_no, blocks.c.sequence_no
                )
            )
            .mappings()
            .all()
        )
        contexts: list[dict[str, Any]] = []
        for index, block in enumerate(block_rows):
            previous = (
                block_rows[index - 1]["content_text"]
                if index > 0 and block_rows[index - 1]["page_id"] == block["page_id"]
                else None
            )
            following = (
                block_rows[index + 1]["content_text"]
                if index + 1 < len(block_rows)
                and block_rows[index + 1]["page_id"] == block["page_id"]
                else None
            )
            contexts.append(
                {
                    **dict(block),
                    "text": "\n".join(
                        value for value in [previous, block["content_text"], following] if value
                    ),
                    "evidence_text": block["content_text"] or "",
                    "evidence_type": "text",
                    "previous_context": previous,
                    "next_context": following,
                    "table_cell_id": None,
                    "figure_id": None,
                    "confidence": 0.85,
                    "method": "rule_evidence_extractor",
                    "is_image_estimate": False,
                }
            )
        table_query = (
            select(
                document_tables.c.id.label("table_id"),
                document_tables.c.document_version_id,
                document_tables.c.page_id,
                document_tables.c.title,
                document_tables.c.caption,
                document_tables.c.bbox,
                table_cells.c.id.label("table_cell_id"),
                table_cells.c.row_index,
                table_cells.c.column_index,
                table_cells.c.cell_role,
                table_cells.c.raw_text,
                table_cells.c.style,
                pages.c.page_no,
            )
            .join(table_cells, table_cells.c.table_id == document_tables.c.id)
            .join(pages, pages.c.id == document_tables.c.page_id)
            .join(DocumentVersion, DocumentVersion.id == document_tables.c.document_version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(Document.project_id == run["project_id"], Document.deleted_at.is_(None))
        )
        if run["search_run_id"] is not None:
            table_query = table_query.where(
                exists(
                    select(1).where(
                        search_results.c.search_run_id == run["search_run_id"],
                        search_results.c.is_included.is_(True),
                        search_results.c.table_id == document_tables.c.id,
                    )
                )
            )
        table_rows = (
            self.db.execute(
                table_query.order_by(
                    document_tables.c.id, table_cells.c.row_index, table_cells.c.column_index
                )
            )
            .mappings()
            .all()
        )
        grouped_rows: dict[tuple[UUID, int], list[dict]] = {}
        for item in table_rows:
            grouped_rows.setdefault((item["table_id"], item["row_index"]), []).append(dict(item))
        for (table_id, row_index), row_cells in grouped_rows.items():
            if row_cells and all(item["cell_role"] == "header" for item in row_cells):
                continue
            segments = []
            for cell_item in row_cells:
                value = str(cell_item["raw_text"] or "").strip()
                header_path = " / ".join((cell_item["style"] or {}).get("header_path", []))
                if value:
                    segments.append(f"{header_path}: {value}" if header_path else value)
            first = row_cells[0]
            contexts.append(
                {
                    "document_version_id": first["document_version_id"],
                    "page_id": first["page_id"],
                    "page_no": first["page_no"],
                    "block_id": None,
                    "table_cell_id": first["table_cell_id"],
                    "figure_id": None,
                    "bbox": first["bbox"],
                    "text": " | ".join(
                        value for value in [first["title"], first["caption"], *segments] if value
                    ),
                    "evidence_text": " | ".join(segments),
                    "evidence_type": "table",
                    "previous_context": first["title"],
                    "next_context": None,
                    "confidence": 0.9,
                    "method": "structured_table_extractor",
                    "is_image_estimate": False,
                    "source_key": f"table={table_id}:row={row_index}",
                }
            )
        figure_query = (
            select(
                figures.c.id.label("figure_id"),
                figures.c.document_version_id,
                figures.c.page_id,
                figures.c.title,
                figures.c.caption,
                figures.c.bbox,
                figures.c.extracted_labels,
                figures.c.semantic_summary,
                figures.c.confidence,
                pages.c.page_no,
            )
            .join(pages, pages.c.id == figures.c.page_id)
            .join(DocumentVersion, DocumentVersion.id == figures.c.document_version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(Document.project_id == run["project_id"], Document.deleted_at.is_(None))
        )
        if run["search_run_id"] is not None:
            figure_query = figure_query.where(
                exists(
                    select(1).where(
                        search_results.c.search_run_id == run["search_run_id"],
                        search_results.c.is_included.is_(True),
                        search_results.c.figure_id == figures.c.id,
                    )
                )
            )
        figure_rows = (
            self.db.execute(figure_query)
            .mappings()
            .all()
        )
        for figure in figure_rows:
            payload = figure["extracted_labels"] or {}
            direct_values = payload.get("direct_values", []) if isinstance(payload, dict) else []
            label_context = " | ".join(
                str(item.get("text") or "")
                for item in (payload.get("labels", []) if isinstance(payload, dict) else [])
                if item.get("text")
                and not re.fullmatch(r"[-+]?\d+(?:\.\d+)?\s*", str(item["text"]))
            )
            all_text = " | ".join(
                value for value in [figure["title"], figure["caption"], label_context] if value
            )
            for value_index, direct in enumerate(direct_values, start=1):
                contexts.append(
                    {
                        "document_version_id": figure["document_version_id"],
                        "page_id": figure["page_id"],
                        "page_no": figure["page_no"],
                        "block_id": None,
                        "table_cell_id": None,
                        "figure_id": figure["figure_id"],
                        "bbox": direct.get("bbox") or figure["bbox"],
                        "text": f"{all_text} | {direct.get('text', '')}",
                        "evidence_text": direct.get("text", ""),
                        "evidence_type": "figure",
                        "previous_context": figure["caption"],
                        "next_context": None,
                        "confidence": float(
                            direct.get("confidence") or figure["confidence"] or 0.7
                        ),
                        "method": "direct_chart_label_extractor",
                        "is_image_estimate": False,
                        "source_key": f"figure={figure['figure_id']}:value={value_index}",
                    }
                )
        count = 0
        for field_index, field in enumerate(field_rows):
            variants = [field["display_name"]]
            if field["source_term_id"]:
                canonical = self.db.scalar(
                    select(terms.c.canonical_name).where(terms.c.id == field["source_term_id"])
                )
                if canonical:
                    variants.append(canonical)
                variants.extend(
                    self.db.scalars(
                        select(aliases.c.alias_text).where(
                            aliases.c.term_id == field["source_term_id"],
                            aliases.c.status == "confirmed",
                        )
                    ).all()
                )
            variants.extend((field["extraction_config"] or {}).get("aliases", []))
            variant_pattern = "|".join(
                re.escape(item) for item in sorted(set(variants), key=len, reverse=True) if item
            )
            if not variant_pattern:
                continue
            pattern = re.compile(
                rf"(?:{variant_pattern}).{{0,50}}?{VALUE_PATTERN}\s*{UNIT_PATTERN}", re.IGNORECASE
            )
            for context in contexts:
                text_value = context["text"] or ""
                for match_no, match in enumerate(pattern.finditer(text_value), start=1):
                    raw_value = match.group("value")
                    parsed = parse_numeric(raw_value)
                    numeric = first_not_none(
                        parsed.get("value"), parsed.get("mean"), parsed.get("mid")
                    )
                    significance_match = re.search(r"(?<=\d)([a-zA-Z]{1,3})$", raw_value)
                    fallback = context.get("source_key") or (
                        f"block={context['block_id']}:page={context['page_no']}"
                    )
                    group_key, timepoint_key = self._dimension_keys(text_value, fallback)
                    dimensions = self._dimension_metadata(text_value)
                    sample_key = f"{context['document_version_id']}:{group_key}:{field['field_key']}:{match_no}"[
                        :255
                    ]
                    record_id = self.db.execute(
                        insert(records)
                        .values(
                            extraction_run_id=run_id,
                            document_version_id=context["document_version_id"],
                            field_definition_id=field["id"],
                            sample_key=sample_key,
                            group_key=group_key[:255],
                            timepoint_key=timepoint_key,
                            raw_value=raw_value,
                            raw_unit_text=match.group("unit"),
                            parsed_value=parsed,
                            normalized_value={},
                            ml_value={"value": numeric} if numeric is not None else {},
                            value_type=parsed["type"],
                            numeric_value=numeric,
                            range_min=parsed.get("min"),
                            range_max=parsed.get("max"),
                            mean_value=parsed.get("mean"),
                            standard_deviation=parsed.get("sd"),
                            significance_marker=(
                                significance_match.group(1) if significance_match else None
                            ),
                            extraction_method=context["method"],
                            confidence=context["confidence"],
                            review_status="pending",
                            is_image_estimate=context["is_image_estimate"],
                            is_missing=False,
                            metadata={
                                "matched_aliases": variants,
                                "treatment_time_linked": True,
                                "source_type": context["evidence_type"],
                                "dimensions": dimensions,
                            },
                        )
                        .returning(records.c.id)
                    ).scalar_one()
                    self.db.execute(
                        insert(evidence).values(
                            extraction_record_id=record_id,
                            document_version_id=context["document_version_id"],
                            page_id=context["page_id"],
                            block_id=context["block_id"],
                            table_cell_id=context["table_cell_id"],
                            figure_id=context["figure_id"],
                            evidence_type=context["evidence_type"],
                            relation_type="supports",
                            previous_context=context["previous_context"],
                            evidence_text=context["evidence_text"],
                            next_context=context["next_context"],
                            bbox=context["bbox"],
                            is_primary=True,
                            confidence=context["confidence"],
                        )
                    )
                    count += 1
            progress(
                5 + 90 * (field_index + 1) / len(field_rows),
                f"extracting_field_{field['field_key']}",
            )
            self.db.commit()
        self.db.execute(
            update(runs)
            .where(runs.c.id == run_id)
            .values(status="completed", completed_at=func.now())
        )
        self.db.commit()
        return {
            "extraction_run_id": str(run_id),
            "field_count": len(field_rows),
            "record_count": count,
        }
