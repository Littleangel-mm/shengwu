import re
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import jieba
from fastapi.encoders import jsonable_encoder
from rapidfuzz import fuzz
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.tables import table
from app.models import ProcessingJob
from app.schemas.workflow import (
    FieldSchemaCreate,
    FieldSchemaUpdate,
    TaskAccepted,
    TermCategoryCreate,
    TermCategoryUpdate,
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

DEFAULT_TERM_CATEGORY_TEMPLATES: tuple[dict[str, str], ...] = (
    {
        "code": "process_parameters",
        "name": "工艺参数",
        "description": "发酵温度、发酵时间、pH、接种量等工艺过程控制参数",
    },
    {
        "code": "chemical_indicators",
        "name": "化学指标",
        "description": "总酸、氨基酸态氮、还原糖等理化与化学成分指标",
    },
    {
        "code": "sensory_evaluation",
        "name": "感官评价",
        "description": "色泽、香气、滋味、体态等感官评价指标",
    },
)

SYNONYM_SIMILARITY_THRESHOLD = 85.0
SYNONYM_MAX_TERMS = 2000
SYNONYM_MAX_CLUSTERS = 50


def _find_root(parent: dict[UUID, UUID], item: UUID) -> UUID:
    root = item
    while parent[root] != root:
        root = parent[root]
    while parent[item] != root:
        parent[item], item = root, parent[item]
    return root


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

    def apply_default_category_template(self, project_id: UUID) -> list[dict]:
        categories = table(self.db, "term_categories")
        existing_codes = set(
            self.db.scalars(
                select(categories.c.code).where(categories.c.project_id == project_id)
            ).all()
        )
        created = False
        for position, template in enumerate(DEFAULT_TERM_CATEGORY_TEMPLATES):
            if template["code"] in existing_codes:
                continue
            self.db.execute(
                insert(categories).values(
                    project_id=project_id,
                    code=template["code"],
                    name=template["name"],
                    description=template["description"],
                    position=position,
                    settings={},
                )
            )
            created = True
        if created:
            self.db.commit()
        return self.list_categories(project_id)

    @staticmethod
    def _normalize_similarity_text(value: str) -> str:
        return re.sub(r"\s+", " ", value.casefold()).strip()

    def suggest_synonyms(
        self,
        project_id: UUID,
        threshold: float = SYNONYM_SIMILARITY_THRESHOLD,
        max_terms: int = SYNONYM_MAX_TERMS,
        max_clusters: int = SYNONYM_MAX_CLUSTERS,
    ) -> list[dict[str, Any]]:
        terms = table(self.db, "terms")
        aliases = table(self.db, "term_aliases")
        categories = table(self.db, "term_categories")
        occurrences = table(self.db, "term_occurrences")
        rows = (
            self.db.execute(
                select(
                    terms.c.id,
                    terms.c.canonical_name,
                    terms.c.normalized_name,
                    terms.c.category_id,
                )
                .where(terms.c.project_id == project_id, terms.c.deleted_at.is_(None))
                .order_by(terms.c.canonical_name)
                .limit(max_terms)
            )
            .mappings()
            .all()
        )
        if len(rows) < 2:
            return []
        term_ids: list[UUID] = [row["id"] for row in rows]
        variants: dict[UUID, set[str]] = {term_id: set() for term_id in term_ids}
        for row in rows:
            for value in (row["canonical_name"], row["normalized_name"]):
                normalized = self._normalize_similarity_text(value or "")
                if normalized:
                    variants[row["id"]].add(normalized)
        for alias in self.db.execute(
            select(aliases.c.term_id, aliases.c.alias_text, aliases.c.normalized_alias).where(
                aliases.c.term_id.in_(term_ids)
            )
        ).mappings():
            for value in (alias["alias_text"], alias["normalized_alias"]):
                normalized = self._normalize_similarity_text(value or "")
                if normalized:
                    variants[alias["term_id"]].add(normalized)
        occurrence_counts: dict[UUID, int] = {
            row["term_id"]: int(row["total"] or 0)
            for row in self.db.execute(
                select(
                    occurrences.c.term_id,
                    func.sum(occurrences.c.occurrence_count).label("total"),
                )
                .where(occurrences.c.term_id.in_(term_ids))
                .group_by(occurrences.c.term_id)
            ).mappings()
        }
        category_names: dict[UUID, str] = {
            row["id"]: row["name"]
            for row in self.db.execute(
                select(categories.c.id, categories.c.name).where(
                    categories.c.project_id == project_id
                )
            ).mappings()
        }
        info: dict[UUID, dict[str, Any]] = {
            row["id"]: {
                "id": row["id"],
                "display_name": row["canonical_name"],
                "category_id": row["category_id"],
                "category": category_names.get(row["category_id"]),
                "occurrence_count": occurrence_counts.get(row["id"], 0),
            }
            for row in rows
        }
        parent: dict[UUID, UUID] = {term_id: term_id for term_id in term_ids}
        edges: list[tuple[UUID, UUID, float]] = []
        for index, left in enumerate(term_ids):
            for right in term_ids[index + 1 :]:
                if variants[left] & variants[right]:
                    score = 100.0
                else:
                    score = max(
                        (
                            float(fuzz.token_set_ratio(a, b))
                            for a in variants[left]
                            for b in variants[right]
                        ),
                        default=0.0,
                    )
                if score >= threshold:
                    parent[_find_root(parent, left)] = _find_root(parent, right)
                    edges.append((left, right, score))
        members_by_root: dict[UUID, list[UUID]] = {}
        for term_id in term_ids:
            members_by_root.setdefault(_find_root(parent, term_id), []).append(term_id)
        score_by_root: dict[UUID, float] = {}
        for left, _right, score in edges:
            root = _find_root(parent, left)
            score_by_root[root] = max(score_by_root.get(root, 0.0), score)
        clusters: list[dict[str, Any]] = []
        for root, members in members_by_root.items():
            if len(members) < 2:
                continue
            term_items = [info[member] for member in members]
            suggested = min(
                term_items,
                key=lambda item: (
                    -item["occurrence_count"],
                    len(item["display_name"]),
                    item["display_name"],
                ),
            )
            clusters.append(
                {
                    "terms": term_items,
                    "suggested_standard": suggested,
                    "similarity": round(score_by_root.get(root, 0.0), 1),
                }
            )
        clusters.sort(key=lambda cluster: (-len(cluster["terms"]), -cluster["similarity"]))
        return clusters[:max_clusters]

    def update_category(
        self, project_id: UUID, category_id: UUID, payload: TermCategoryUpdate
    ) -> dict:
        categories = table(self.db, "term_categories")
        values = payload.model_dump(exclude_unset=True)
        if not values:
            row = self.db.execute(
                select(categories).where(
                    categories.c.id == category_id,
                    categories.c.project_id == project_id,
                )
            ).mappings().one_or_none()
        else:
            row = (
                self.db.execute(
                    update(categories)
                    .where(
                        categories.c.id == category_id,
                        categories.c.project_id == project_id,
                    )
                    .values(**values)
                    .returning(categories)
                )
                .mappings()
                .one_or_none()
            )
        if not row:
            raise AppError(code="term_category_not_found", message="术语分类不存在", status_code=404)
        self.db.commit()
        return dict(row)

    def delete_category(self, project_id: UUID, category_id: UUID) -> dict:
        categories = table(self.db, "term_categories")
        terms = table(self.db, "terms")
        category_exists = self.db.scalar(
            select(categories.c.id).where(
                categories.c.id == category_id,
                categories.c.project_id == project_id,
            )
        )
        if not category_exists:
            raise AppError(code="term_category_not_found", message="术语分类不存在", status_code=404)
        term_count = (
            self.db.scalar(
                select(func.count()).select_from(terms).where(terms.c.category_id == category_id)
            )
            or 0
        )
        if term_count:
            raise AppError(
                code="term_category_in_use",
                message="术语分类仍被术语使用，无法删除",
                status_code=409,
            )
        self.db.execute(
            delete(categories).where(
                categories.c.id == category_id,
                categories.c.project_id == project_id,
            )
        )
        self.db.commit()
        return {"id": category_id, "status": "deleted"}

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
        self,
        project_id: UUID,
        category_id: UUID | None,
        status: str | None,
        is_selected: bool | None,
        offset: int,
        limit: int,
    ) -> tuple[list[dict], int]:
        terms = table(self.db, "terms")
        aliases = table(self.db, "term_aliases")
        filters = [terms.c.project_id == project_id, terms.c.deleted_at.is_(None)]
        if category_id:
            filters.append(terms.c.category_id == category_id)
        if status is not None:
            filters.append(terms.c.status == status)
        if is_selected is not None:
            filters.append(terms.c.is_selected == is_selected)
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
        items = [dict(row) for row in rows]
        aliases_by_term: dict[UUID, list[dict]] = {item["id"]: [] for item in items}
        if aliases_by_term:
            for alias in self.db.execute(
                select(aliases)
                .where(aliases.c.term_id.in_(aliases_by_term))
                .order_by(aliases.c.created_at)
            ).mappings():
                aliases_by_term[alias["term_id"]].append(dict(alias))
        for item in items:
            item["aliases"] = aliases_by_term[item["id"]]
        return items, total

    def update_term(
        self,
        project_id: UUID,
        term_id: UUID,
        payload: TermUpdate,
        actor_id: UUID | None,
    ) -> dict:
        terms = table(self.db, "terms")
        categories = table(self.db, "term_categories")
        aliases = table(self.db, "term_aliases")
        self.get_term(project_id, term_id)
        values = payload.model_dump(exclude_unset=True)
        alias_values = values.pop("aliases", None)
        if "canonical_name" in values:
            values["canonical_name"] = values["canonical_name"].strip()
            values["normalized_name"] = values["canonical_name"].casefold().strip()
        if "category_id" in values:
            category_exists = self.db.scalar(
                select(categories.c.id).where(
                    categories.c.id == values["category_id"],
                    categories.c.project_id == project_id,
                )
            )
            if not category_exists:
                raise AppError(
                    code="term_category_not_found", message="术语分类不存在", status_code=422
                )
        try:
            if values:
                self.db.execute(
                    update(terms)
                    .where(
                        terms.c.id == term_id,
                        terms.c.project_id == project_id,
                        terms.c.deleted_at.is_(None),
                    )
                    .values(**values)
                )
            if alias_values is not None:
                self.db.execute(delete(aliases).where(aliases.c.term_id == term_id))
                unique_aliases: dict[str, str] = {}
                for value in alias_values:
                    stripped = value.strip()
                    if stripped:
                        unique_aliases.setdefault(stripped.casefold(), stripped)
                if unique_aliases:
                    self.db.execute(
                        insert(aliases),
                        [
                            {
                                "term_id": term_id,
                                "alias_text": value,
                                "normalized_alias": normalized,
                                "source": "manual",
                                "status": "confirmed",
                                "created_by": actor_id,
                            }
                            for normalized, value in unique_aliases.items()
                        ],
                    )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self.get_term(project_id, term_id)

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

    @staticmethod
    def _discovery_candidates(
        counter: Counter[str], min_occurrences: int, max_candidates: int
    ) -> list[tuple[str, int]]:
        return [
            (token, count)
            for token, count in counter.most_common(max_candidates)
            if count >= min_occurrences
        ]

    def discover(
        self,
        search_run_id: UUID,
        progress: Callable[[float, str], None],
        min_occurrences: int = 2,
        max_candidates: int = 500,
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
        candidates = self._discovery_candidates(counter, min_occurrences, max_candidates)
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

    @staticmethod
    def _field_values(schema_id: UUID, item: Any, position: int) -> dict[str, Any]:
        return {
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
            "position": position,
            "extraction_config": item.extraction_config,
            "validation_rules": item.validation_rules,
            "display_config": {},
        }

    def _validate_field_sources(self, project_id: UUID, source_ids: set[UUID]) -> None:
        if not source_ids:
            return
        terms = table(self.db, "terms")
        valid_ids = set(
            self.db.scalars(
                select(terms.c.id).where(
                    terms.c.id.in_(source_ids),
                    terms.c.project_id == project_id,
                    terms.c.deleted_at.is_(None),
                )
            ).all()
        )
        if valid_ids != source_ids:
            raise AppError(
                code="field_source_term_invalid",
                message="字段引用的术语不存在或不属于当前项目",
                status_code=422,
            )

    def _validate_field_inputs(self, project_id: UUID, field_items: list[Any]) -> None:
        field_keys = [item.field_key for item in field_items]
        if len(field_keys) != len(set(field_keys)):
            raise AppError(
                code="field_key_duplicate",
                message="字段标识 field_key 必须唯一",
                status_code=422,
            )
        self._validate_field_sources(
            project_id,
            {item.source_term_id for item in field_items if item.source_term_id is not None},
        )

    def create_field_schema(
        self, project_id: UUID, payload: FieldSchemaCreate, actor_id: UUID | None
    ) -> dict:
        schemas = table(self.db, "field_schemas")
        fields = table(self.db, "field_definitions")
        self._validate_field_inputs(project_id, payload.fields)
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
                self._field_values(schema_id, item, index)
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

    def update_field_schema(
        self, project_id: UUID, schema_id: UUID, payload: FieldSchemaUpdate
    ) -> dict:
        schemas = table(self.db, "field_schemas")
        fields = table(self.db, "field_definitions")
        schema_status = self.db.scalar(
            select(schemas.c.status).where(
                schemas.c.id == schema_id,
                schemas.c.project_id == project_id,
            )
        )
        if schema_status is None:
            raise AppError(code="field_schema_not_found", message="字段方案不存在", status_code=404)
        if schema_status != "draft":
            raise AppError(
                code="field_schema_frozen",
                message="已冻结的字段方案禁止修改",
                status_code=409,
            )
        self._validate_field_inputs(project_id, payload.fields)
        try:
            updated_id = self.db.scalar(
                update(schemas)
                .where(
                    schemas.c.id == schema_id,
                    schemas.c.project_id == project_id,
                    schemas.c.status == "draft",
                )
                .values(name=payload.name, settings=payload.settings)
                .returning(schemas.c.id)
            )
            if not updated_id:
                raise AppError(
                    code="field_schema_frozen",
                    message="已冻结的字段方案禁止修改",
                    status_code=409,
                )
            self.db.execute(delete(fields).where(fields.c.field_schema_id == schema_id))
            self.db.execute(
                insert(fields),
                [
                    self._field_values(schema_id, item, index)
                    for index, item in enumerate(payload.fields)
                ],
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self.get_field_schema(project_id, schema_id)

    def freeze_field_schema(self, project_id: UUID, schema_id: UUID, actor_id: UUID | None) -> dict:
        schemas = table(self.db, "field_schemas")
        fields = table(self.db, "field_definitions")
        existing_status = self.db.scalar(
            select(schemas.c.status).where(
                schemas.c.id == schema_id,
                schemas.c.project_id == project_id,
            )
        )
        if existing_status is None:
            raise AppError(code="field_schema_not_found", message="字段方案不存在", status_code=404)
        if existing_status != "draft":
            raise AppError(
                code="field_schema_not_freezable",
                message="字段方案已冻结",
                status_code=409,
            )
        field_rows = self.db.execute(
            select(fields.c.field_key, fields.c.source_term_id).where(
                fields.c.field_schema_id == schema_id
            )
        ).mappings().all()
        if not field_rows:
            raise AppError(
                code="field_schema_empty",
                message="字段方案至少需要一个字段才能冻结",
                status_code=422,
            )
        field_keys = [row["field_key"] for row in field_rows]
        if len(field_keys) != len(set(field_keys)):
            raise AppError(
                code="field_key_duplicate",
                message="字段标识 field_key 必须唯一",
                status_code=422,
            )
        self._validate_field_sources(
            project_id,
            {row["source_term_id"] for row in field_rows if row["source_term_id"] is not None},
        )
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
