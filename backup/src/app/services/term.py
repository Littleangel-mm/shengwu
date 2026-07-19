import re
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import jieba
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.tables import table
from app.models import ProcessingJob
from app.schemas.workflow import (
    FieldSchemaCreate,
    TaskAccepted,
    TermCategoryCreate,
    TermCreate,
    TermDiscoveryCreate,
    TermMerge,
    TermSplit,
    TermUpdate,
)

STOPWORDS = {
    "本文",
    "研究",
    "结果",
    "方法",
    "进行",
    "分析",
    "通过",
    "不同",
    "相关",
    "影响",
    "the",
    "and",
    "with",
    "from",
    "that",
    "this",
    "were",
    "was",
    "for",
    "using",
}


class TermService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_category(self, project_id: UUID, payload: TermCategoryCreate) -> dict:
        categories = table(self.db, "term_categories")
        row = (
            self.db.execute(
                insert(categories)
                .values(
                    project_id=project_id,
                    code=payload.code,
                    name=payload.name,
                    description=payload.description,
                    settings={},
                )
                .returning(categories)
            )
            .mappings()
            .one()
        )
        self.db.commit()
        return dict(row)

    def list_categories(self, project_id: UUID) -> list[dict]:
        categories = table(self.db, "term_categories")
        return [
            dict(row)
            for row in self.db.execute(
                select(categories)
                .where(categories.c.project_id == project_id)
                .order_by(categories.c.position, categories.c.name)
            ).mappings()
        ]

    def create_term(self, project_id: UUID, payload: TermCreate, actor_id: UUID | None) -> dict:
        terms = table(self.db, "terms")
        aliases = table(self.db, "term_aliases")
        term_id = self.db.execute(
            insert(terms)
            .values(
                project_id=project_id,
                category_id=payload.category_id,
                canonical_name=payload.canonical_name.strip(),
                normalized_name=payload.canonical_name.casefold().strip(),
                definition=payload.definition,
                language=payload.language,
                data_type=payload.data_type,
                semantic_role=payload.semantic_role,
                status=payload.status,
                is_selected=payload.is_selected,
                metadata={},
                created_by=actor_id,
            )
            .returning(terms.c.id)
        ).scalar_one()
        if payload.aliases:
            self.db.execute(
                insert(aliases),
                [
                    {
                        "term_id": term_id,
                        "alias_text": value.strip(),
                        "normalized_alias": value.casefold().strip(),
                        "source": "manual",
                        "status": "confirmed",
                        "created_by": actor_id,
                    }
                    for value in dict.fromkeys(payload.aliases)
                    if value.strip()
                ],
            )
        self.db.commit()
        return self.get_term(project_id, term_id)

    def get_term(self, project_id: UUID, term_id: UUID) -> dict:
        terms = table(self.db, "terms")
        aliases = table(self.db, "term_aliases")
        row = (
            self.db.execute(
                select(terms).where(
                    terms.c.id == term_id,
                    terms.c.project_id == project_id,
                    terms.c.deleted_at.is_(None),
                )
            )
            .mappings()
            .one_or_none()
        )
        if not row:
            raise AppError(code="term_not_found", message="词元不存在", status_code=404)
        result = dict(row)
        result["aliases"] = [
            dict(item)
            for item in self.db.execute(
                select(aliases).where(aliases.c.term_id == term_id).order_by(aliases.c.created_at)
            ).mappings()
        ]
        return result

    def list_terms(
        self, project_id: UUID, category_id: UUID | None, offset: int, limit: int
    ) -> tuple[list[dict], int]:
        terms = table(self.db, "terms")
        filters = [terms.c.project_id == project_id, terms.c.deleted_at.is_(None)]
        if category_id:
            filters.append(terms.c.category_id == category_id)
        total = self.db.scalar(select(func.count()).select_from(terms).where(*filters)) or 0
        rows = (
            self.db.execute(
                select(terms)
                .where(*filters)
                .order_by(terms.c.is_selected.desc(), terms.c.canonical_name)
                .offset(offset)
                .limit(limit)
            )
            .mappings()
            .all()
        )
        return [dict(row) for row in rows], total

    def update_term(self, project_id: UUID, term_id: UUID, payload: TermUpdate) -> dict:
        terms = table(self.db, "terms")
        values = payload.model_dump(exclude_unset=True)
        if "canonical_name" in values:
            values["normalized_name"] = values["canonical_name"].casefold().strip()
        row = (
            self.db.execute(
                update(terms)
                .where(
                    terms.c.id == term_id,
                    terms.c.project_id == project_id,
                    terms.c.deleted_at.is_(None),
                )
                .values(**values)
                .returning(terms)
            )
            .mappings()
            .one_or_none()
        )
        if not row:
            raise AppError(code="term_not_found", message="词元不存在", status_code=404)
        self.db.commit()
        return dict(row)

    def delete_term(self, project_id: UUID, term_id: UUID, actor_id: UUID | None) -> dict:
        terms = table(self.db, "terms")
        events = table(self.db, "term_review_events")
        existing = self.get_term(project_id, term_id)
        self.db.execute(
            update(terms)
            .where(terms.c.id == term_id, terms.c.project_id == project_id)
            .values(status="deleted", is_selected=False, deleted_at=datetime.now(UTC))
        )
        self.db.execute(
            insert(events).values(
                project_id=project_id,
                term_id=term_id,
                action="delete",
                related_term_ids=[],
                before_value=jsonable_encoder(existing),
                after_value={"status": "deleted"},
                actor_id=actor_id,
            )
        )
        self.db.commit()
        return {"id": term_id, "status": "deleted"}

    def merge_terms(self, project_id: UUID, payload: TermMerge, actor_id: UUID | None) -> dict:
        terms = table(self.db, "terms")
        aliases = table(self.db, "term_aliases")
        occurrences = table(self.db, "term_occurrences")
        fields = table(self.db, "field_definitions")
        events = table(self.db, "term_review_events")
        target = self.get_term(project_id, payload.target_term_id)
        source_ids = [
            item
            for item in dict.fromkeys(payload.source_term_ids)
            if item != payload.target_term_id
        ]
        if not source_ids:
            raise AppError(
                code="merge_sources_required", message="合并来源词元为空", status_code=422
            )
        sources = [self.get_term(project_id, source_id) for source_id in source_ids]
        existing_aliases = {
            value.casefold()
            for value in self.db.scalars(
                select(aliases.c.alias_text).where(aliases.c.term_id == payload.target_term_id)
            ).all()
        }
        candidates: list[str] = []
        for source in sources:
            candidates.append(source["canonical_name"])
            candidates.extend(item["alias_text"] for item in source.get("aliases", []))
        for value in candidates:
            normalized = value.casefold().strip()
            if not normalized or normalized in existing_aliases:
                continue
            self.db.execute(
                insert(aliases).values(
                    term_id=payload.target_term_id,
                    alias_text=value.strip(),
                    normalized_alias=normalized,
                    source="manual_merge",
                    status="confirmed",
                    created_by=actor_id,
                )
            )
            existing_aliases.add(normalized)
        self.db.execute(
            update(occurrences)
            .where(occurrences.c.term_id.in_(source_ids))
            .values(term_id=payload.target_term_id)
        )
        self.db.execute(
            update(fields)
            .where(fields.c.source_term_id.in_(source_ids))
            .values(source_term_id=payload.target_term_id)
        )
        for source in sources:
            metadata = {
                **(source.get("metadata") or {}),
                "merged_into_term_id": str(payload.target_term_id),
            }
            self.db.execute(
                update(terms)
                .where(terms.c.id == source["id"])
                .values(status="merged", is_selected=False, metadata=metadata)
            )
        self.db.execute(
            insert(events).values(
                project_id=project_id,
                term_id=payload.target_term_id,
                action="merge",
                related_term_ids=[str(item) for item in source_ids],
                before_value=jsonable_encoder({"target": target, "sources": sources}),
                after_value={"target_term_id": str(payload.target_term_id)},
                reason=payload.reason,
                actor_id=actor_id,
            )
        )
        self.db.commit()
        return self.get_term(project_id, payload.target_term_id)

    def split_term(
        self,
        project_id: UUID,
        term_id: UUID,
        payload: TermSplit,
        actor_id: UUID | None,
    ) -> list[dict]:
        terms = table(self.db, "terms")
        events = table(self.db, "term_review_events")
        source = self.get_term(project_id, term_id)
        children = []
        for child in payload.children:
            children.append(
                self.create_term(
                    project_id,
                    TermCreate(
                        category_id=child.category_id,
                        canonical_name=child.canonical_name,
                        aliases=child.aliases,
                        semantic_role=child.semantic_role,
                        data_type=child.data_type,
                        status="confirmed",
                        is_selected=True,
                    ),
                    actor_id,
                )
            )
        metadata = {
            **(source.get("metadata") or {}),
            "split_into_term_ids": [str(child["id"]) for child in children],
        }
        self.db.execute(
            update(terms)
            .where(terms.c.id == term_id)
            .values(status="split", is_selected=False, metadata=metadata)
        )
        self.db.execute(
            insert(events).values(
                project_id=project_id,
                term_id=term_id,
                action="split",
                related_term_ids=[str(child["id"]) for child in children],
                before_value=jsonable_encoder(source),
                after_value=jsonable_encoder({"children": children}),
                reason=payload.reason,
                actor_id=actor_id,
            )
        )
        self.db.commit()
        return children

    def enqueue_discovery(
        self, project_id: UUID, payload: TermDiscoveryCreate, actor_id: UUID | None
    ) -> TaskAccepted:
        job = ProcessingJob(
            project_id=project_id,
            job_type="discover_terms",
            status="queued",
            progress_percent=0,
            current_stage="waiting",
            requested_config={
                "search_run_id": str(payload.search_run_id),
                "min_occurrences": payload.min_occurrences,
                "max_candidates": payload.max_candidates,
            },
            result_summary={},
            requested_by=actor_id,
        )
        self.db.add(job)
        self.db.commit()
        return TaskAccepted(resource_id=payload.search_run_id, job_id=job.id)

    @staticmethod
    def _tokens(text_value: str) -> list[str]:
        values = []
        for token in jieba.cut(text_value):
            value = token.strip().casefold()
            if len(value) < 2 or value in STOPWORDS:
                continue
            if re.fullmatch(r"[\W_\d.%-]+", value, flags=re.UNICODE):
                continue
            values.append(value)
        return values

    def discover(
        self, search_run_id: UUID, progress: Callable[[float, str], None]
    ) -> dict[str, Any]:
        runs = table(self.db, "search_runs")
        results = table(self.db, "search_results")
        categories = table(self.db, "term_categories")
        terms = table(self.db, "terms")
        occurrences = table(self.db, "term_occurrences")
        run = (
            self.db.execute(select(runs).where(runs.c.id == search_run_id)).mappings().one_or_none()
        )
        if not run:
            raise AppError(code="search_run_not_found", message="检索任务不存在", status_code=404)
        rows = (
            self.db.execute(
                select(results).where(
                    results.c.search_run_id == search_run_id, results.c.is_included.is_(True)
                )
            )
            .mappings()
            .all()
        )
        counter: Counter[str] = Counter()
        token_rows: dict[str, list[dict]] = {}
        for index, row in enumerate(rows):
            text_value = " ".join(
                filter(None, [row["previous_context"], row["matched_context"], row["next_context"]])
            )
            for token in self._tokens(text_value):
                counter[token] += 1
                token_rows.setdefault(token, []).append(dict(row))
            if index % 100 == 0:
                progress(10 + 50 * index / max(len(rows), 1), "tokenizing")

        category_id = self.db.scalar(
            select(categories.c.id).where(
                categories.c.project_id == run["project_id"], categories.c.code == "domain_terms"
            )
        )
        if not category_id:
            category_id = self.db.execute(
                insert(categories)
                .values(
                    project_id=run["project_id"],
                    code="domain_terms",
                    name="领域术语",
                    position=0,
                    settings={},
                )
                .returning(categories.c.id)
            ).scalar_one()
        min_count = 2
        candidates = [
            (token, count) for token, count in counter.most_common(500) if count >= min_count
        ]
        created = 0
        for index, (token, count) in enumerate(candidates):
            term_id = self.db.scalar(
                select(terms.c.id).where(
                    terms.c.project_id == run["project_id"],
                    terms.c.category_id == category_id,
                    func.lower(terms.c.canonical_name) == token,
                    terms.c.deleted_at.is_(None),
                )
            )
            if not term_id:
                term_id = self.db.execute(
                    insert(terms)
                    .values(
                        project_id=run["project_id"],
                        category_id=category_id,
                        canonical_name=token,
                        normalized_name=token,
                        status="candidate",
                        is_selected=False,
                        confidence=min(0.99, 0.5 + count / 20),
                        metadata={"frequency": count, "source_search_run_id": str(search_run_id)},
                    )
                    .returning(terms.c.id)
                ).scalar_one()
                created += 1
            sample_rows = token_rows[token][:20]
            occurrence_values = [
                {
                    "project_id": run["project_id"],
                    "term_id": term_id,
                    "suggested_category_id": category_id,
                    "document_version_id": item["document_version_id"],
                    "page_id": item["page_id"],
                    "block_id": item["block_id"],
                    "original_text": token,
                    "normalized_text": token,
                    "context_text": item["matched_context"],
                    "occurrence_count": 1,
                    "extraction_method": "frequency_discovery",
                    "confidence": min(0.99, 0.5 + count / 20),
                    "metadata": {},
                }
                for item in sample_rows
                if item["block_id"]
            ]
            if occurrence_values:
                self.db.execute(insert(occurrences), occurrence_values)
            if index % 50 == 0:
                progress(60 + 35 * index / max(len(candidates), 1), "saving_candidates")
        self.db.commit()
        return {
            "search_run_id": str(search_run_id),
            "candidate_count": len(candidates),
            "created_count": created,
        }

    def create_field_schema(
        self, project_id: UUID, payload: FieldSchemaCreate, actor_id: UUID | None
    ) -> dict:
        schemas = table(self.db, "field_schemas")
        fields = table(self.db, "field_definitions")
        version_no = (
            self.db.scalar(
                select(func.max(schemas.c.version_no)).where(schemas.c.project_id == project_id)
            )
            or 0
        ) + 1
        schema_id = self.db.execute(
            insert(schemas)
            .values(
                project_id=project_id,
                version_no=version_no,
                name=payload.name,
                status="draft",
                source_search_run_id=payload.source_search_run_id,
                settings=payload.settings,
                created_by=actor_id,
            )
            .returning(schemas.c.id)
        ).scalar_one()
        self.db.execute(
            insert(fields),
            [
                {
                    "field_schema_id": schema_id,
                    "source_term_id": item.source_term_id,
                    "field_key": item.field_key,
                    "display_name": item.display_name,
                    "category_code": item.category_code,
                    "semantic_role": item.semantic_role,
                    "data_type": item.data_type,
                    "preferred_unit_id": item.preferred_unit_id,
                    "indicator_direction": item.indicator_direction,
                    "is_required": item.is_required,
                    "is_identifier": item.is_identifier,
                    "include_in_model": item.include_in_model,
                    "include_in_score": item.include_in_score,
                    "position": index,
                    "extraction_config": item.extraction_config,
                    "validation_rules": item.validation_rules,
                    "display_config": {},
                }
                for index, item in enumerate(payload.fields)
            ],
        )
        self.db.commit()
        return self.get_field_schema(project_id, schema_id)

    def get_field_schema(self, project_id: UUID, schema_id: UUID) -> dict:
        schemas = table(self.db, "field_schemas")
        fields = table(self.db, "field_definitions")
        row = (
            self.db.execute(
                select(schemas).where(schemas.c.id == schema_id, schemas.c.project_id == project_id)
            )
            .mappings()
            .one_or_none()
        )
        if not row:
            raise AppError(code="field_schema_not_found", message="字段方案不存在", status_code=404)
        result = dict(row)
        result["fields"] = [
            dict(item)
            for item in self.db.execute(
                select(fields)
                .where(fields.c.field_schema_id == schema_id)
                .order_by(fields.c.position)
            ).mappings()
        ]
        return result

    def list_field_schemas(self, project_id: UUID) -> list[dict]:
        schemas = table(self.db, "field_schemas")
        return [
            dict(row)
            for row in self.db.execute(
                select(schemas)
                .where(schemas.c.project_id == project_id)
                .order_by(schemas.c.version_no.desc())
            ).mappings()
        ]

    def freeze_field_schema(self, project_id: UUID, schema_id: UUID, actor_id: UUID | None) -> dict:
        schemas = table(self.db, "field_schemas")
        row = (
            self.db.execute(
                update(schemas)
                .where(
                    schemas.c.id == schema_id,
                    schemas.c.project_id == project_id,
                    schemas.c.status == "draft",
                )
                .values(status="frozen", frozen_by=actor_id, frozen_at=func.now())
                .returning(schemas)
            )
            .mappings()
            .one_or_none()
        )
        if not row:
            raise AppError(
                code="field_schema_not_freezable", message="字段方案不存在或已冻结", status_code=409
            )
        self.db.commit()
        return dict(row)
