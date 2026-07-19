from collections.abc import Callable
from typing import Any
from uuid import UUID

from rapidfuzz.fuzz import partial_ratio
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.tables import table
from app.models import Document, DocumentVersion, ProcessingJob
from app.schemas.workflow import SearchCreate, TaskAccepted


class SearchService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self, project_id: UUID, payload: SearchCreate, actor_id: UUID | None
    ) -> TaskAccepted:
        projects = table(self.db, "projects")
        if not self.db.scalar(
            select(projects.c.id).where(
                projects.c.id == project_id, projects.c.deleted_at.is_(None)
            )
        ):
            raise AppError(code="project_not_found", message="项目不存在", status_code=404)
        runs = table(self.db, "search_runs")
        terms = table(self.db, "search_terms")
        run_id = self.db.execute(
            insert(runs)
            .values(
                project_id=project_id,
                name=payload.name,
                logic_operator=payload.logic_operator,
                match_scope=payload.match_scope,
                search_mode=payload.search_mode,
                configuration={
                    "fuzzy_threshold": payload.fuzzy_threshold,
                    "semantic_threshold": payload.semantic_threshold,
                    "semantic_engine": "local_lsa_v1",
                },
                status="queued",
                created_by=actor_id,
            )
            .returning(runs.c.id)
        ).scalar_one()
        self.db.execute(
            insert(terms),
            [
                {
                    "search_run_id": run_id,
                    "position": index,
                    "term_text": value.strip(),
                    "normalized_text": value.strip().casefold(),
                    "is_required": True,
                    "aliases": [],
                    "options": {},
                }
                for index, value in enumerate(dict.fromkeys(payload.terms))
                if value.strip()
            ],
        )
        job = ProcessingJob(
            project_id=project_id,
            job_type="execute_search",
            status="queued",
            progress_percent=0,
            current_stage="waiting",
            idempotency_key=f"execute_search:{run_id}",
            requested_config={"search_run_id": str(run_id)},
            result_summary={},
            requested_by=actor_id,
        )
        self.db.add(job)
        self.db.commit()
        return TaskAccepted(resource_id=run_id, job_id=job.id)

    def list_runs(self, project_id: UUID, offset: int, limit: int) -> tuple[list[dict], int]:
        runs = table(self.db, "search_runs")
        terms = table(self.db, "search_terms")
        results = table(self.db, "search_results")
        total = (
            self.db.scalar(
                select(func.count()).select_from(runs).where(runs.c.project_id == project_id)
            )
            or 0
        )
        rows = (
            self.db.execute(
                select(runs)
                .where(runs.c.project_id == project_id)
                .order_by(runs.c.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
            .mappings()
            .all()
        )
        items = [dict(row) for row in rows]
        run_ids = [item["id"] for item in items]
        if run_ids:
            term_rows = self.db.execute(
                select(terms.c.search_run_id, terms.c.term_text)
                .where(terms.c.search_run_id.in_(run_ids))
                .order_by(terms.c.search_run_id, terms.c.position)
            ).all()
            result_counts: dict[UUID, int] = {}
            for search_run_id, result_count in self.db.execute(
                select(results.c.search_run_id, func.count())
                .where(results.c.search_run_id.in_(run_ids))
                .group_by(results.c.search_run_id)
            ):
                result_counts[search_run_id] = int(result_count)
            terms_by_run: dict[UUID, list[str]] = {}
            for search_run_id, term_text in term_rows:
                terms_by_run.setdefault(search_run_id, []).append(term_text)
            for item in items:
                item["terms"] = terms_by_run.get(item["id"], [])
                item["result_count"] = result_counts.get(item["id"], 0)
        return items, total

    def list_results(
        self, project_id: UUID, run_id: UUID, offset: int, limit: int
    ) -> tuple[list[dict], int]:
        runs = table(self.db, "search_runs")
        results = table(self.db, "search_results")
        pages = table(self.db, "document_pages")
        if not self.db.scalar(
            select(runs.c.id).where(runs.c.id == run_id, runs.c.project_id == project_id)
        ):
            raise AppError(code="search_run_not_found", message="检索任务不存在", status_code=404)
        total = (
            self.db.scalar(
                select(func.count()).select_from(results).where(results.c.search_run_id == run_id)
            )
            or 0
        )
        rows = (
            self.db.execute(
                select(
                    results,
                    pages.c.page_no,
                    Document.id.label("document_id"),
                    Document.title.label("document_title"),
                )
                .join(pages, pages.c.id == results.c.page_id)
                .join(
                    DocumentVersion,
                    DocumentVersion.id == results.c.document_version_id,
                )
                .join(Document, Document.id == DocumentVersion.document_id)
                .where(results.c.search_run_id == run_id)
                .order_by(results.c.result_no)
                .offset(offset)
                .limit(limit)
            )
            .mappings()
            .all()
        )
        return [dict(row) for row in rows], total

    def review_result(
        self, project_id: UUID, run_id: UUID, result_id: UUID, payload: dict, actor_id: UUID | None
    ) -> dict:
        runs = table(self.db, "search_runs")
        results = table(self.db, "search_results")
        if not self.db.scalar(
            select(runs.c.id).where(runs.c.id == run_id, runs.c.project_id == project_id)
        ):
            raise AppError(code="search_run_not_found", message="检索任务不存在", status_code=404)
        row = (
            self.db.execute(
                update(results)
                .where(results.c.id == result_id, results.c.search_run_id == run_id)
                .values(**payload, reviewed_by=actor_id, reviewed_at=func.now())
                .returning(results)
            )
            .mappings()
            .one_or_none()
        )
        if not row:
            raise AppError(
                code="search_result_not_found", message="检索结果不存在", status_code=404
            )
        self.db.commit()
        return dict(row)

    @staticmethod
    def _term_match(
        text_value: str,
        term: dict,
        mode: str,
        threshold: int,
        semantic_score: float = 0,
        semantic_threshold: float = 0.18,
    ) -> tuple[bool, float, str | None]:
        normalized = text_value.casefold()
        variants = [term["term_text"], *(term.get("aliases") or [])]
        best_score = 0.0
        best_variant = None
        for variant in variants:
            candidate = str(variant).casefold().strip()
            if not candidate:
                continue
            if candidate in normalized and mode != "semantic":
                return True, 100.0, str(variant)
            if mode in {"fuzzy", "hybrid"}:
                score = float(partial_ratio(candidate, normalized))
                if score > best_score:
                    best_score, best_variant = score, str(variant)
        semantic_match = semantic_score >= semantic_threshold
        if mode == "semantic":
            return semantic_match, semantic_score * 100, best_variant
        if mode == "hybrid" and semantic_match:
            return True, max(best_score, semantic_score * 100), best_variant
        return best_score >= threshold, best_score, best_variant

    @staticmethod
    def _semantic_scores(texts: list[str], terms: list[str]) -> list[list[float]]:
        if not texts or not terms:
            return [[0.0 for _ in terms] for _ in texts]
        corpus = [*texts, *terms]
        char_vectorizer = TfidfVectorizer(
            analyzer="char_wb", ngram_range=(2, 5), min_df=1, max_features=30000
        )
        char_matrix = char_vectorizer.fit_transform(corpus)
        text_count = len(texts)
        char_scores = cosine_similarity(char_matrix[:text_count], char_matrix[text_count:])
        try:
            word_vectorizer = TfidfVectorizer(
                analyzer="word", ngram_range=(1, 2), min_df=1, max_features=30000
            )
            word_matrix = word_vectorizer.fit_transform(corpus)
            components = min(128, word_matrix.shape[0] - 1, word_matrix.shape[1] - 1)
            if components < 2:
                return char_scores.tolist()
            latent = TruncatedSVD(n_components=components, random_state=42).fit_transform(
                word_matrix
            )
            latent_scores = cosine_similarity(latent[:text_count], latent[text_count:])
            return (0.45 * char_scores + 0.55 * latent_scores.clip(min=0)).tolist()
        except ValueError:
            return char_scores.tolist()

    def execute(self, run_id: UUID, progress: Callable[[float, str], None]) -> dict[str, Any]:
        runs = table(self.db, "search_runs")
        terms_table = table(self.db, "search_terms")
        results = table(self.db, "search_results")
        blocks = table(self.db, "document_blocks")
        pages = table(self.db, "document_pages")
        run = self.db.execute(select(runs).where(runs.c.id == run_id)).mappings().one_or_none()
        if not run:
            raise AppError(code="search_run_not_found", message="检索任务不存在", status_code=404)
        term_rows = [
            dict(row)
            for row in self.db.execute(
                select(terms_table)
                .where(terms_table.c.search_run_id == run_id)
                .order_by(terms_table.c.position)
            ).mappings()
        ]
        if not term_rows:
            raise AppError(code="search_terms_missing", message="检索词为空", status_code=422)
        self.db.execute(delete(results).where(results.c.search_run_id == run_id))
        self.db.execute(update(runs).where(runs.c.id == run_id).values(status="running"))
        self.db.commit()

        rows = (
            self.db.execute(
                select(
                    blocks.c.id.label("block_id"),
                    blocks.c.document_version_id,
                    blocks.c.page_id,
                    blocks.c.sequence_no,
                    blocks.c.content_text,
                    blocks.c.bbox,
                    pages.c.page_no,
                )
                .join(pages, pages.c.id == blocks.c.page_id)
                .join(DocumentVersion, DocumentVersion.id == blocks.c.document_version_id)
                .join(Document, Document.id == DocumentVersion.document_id)
                .where(Document.project_id == run["project_id"], Document.deleted_at.is_(None))
                .order_by(blocks.c.document_version_id, pages.c.page_no, blocks.c.sequence_no)
            )
            .mappings()
            .all()
        )
        by_document: dict[UUID, list[dict]] = {}
        for row in rows:
            by_document.setdefault(row["document_version_id"], []).append(dict(row))

        scope = run["match_scope"]
        units: list[dict[str, Any]] = []
        for document_rows in by_document.values():
            if scope == "evidence_block":
                units.extend(
                    {
                        "text": str(row["content_text"] or ""),
                        "source_rows": [row],
                        "document_rows": document_rows,
                    }
                    for row in document_rows
                )
            elif scope == "page":
                page_groups: dict[UUID, list[dict]] = {}
                for source_row in document_rows:
                    page_groups.setdefault(source_row["page_id"], []).append(source_row)
                units.extend(
                    {
                        "text": "\n".join(str(row["content_text"] or "") for row in page_rows),
                        "source_rows": page_rows,
                        "document_rows": document_rows,
                    }
                    for page_rows in page_groups.values()
                )
            else:
                units.append(
                    {
                        "text": "\n".join(
                            str(row["content_text"] or "") for row in document_rows
                        ),
                        "source_rows": document_rows,
                        "document_rows": document_rows,
                    }
                )

        unit_texts = [unit["text"] for unit in units]
        semantic_matrix = self._semantic_scores(
            unit_texts, [str(row["term_text"]) for row in term_rows]
        )
        result_no = 0
        inserts = []
        threshold = int((run["configuration"] or {}).get("fuzzy_threshold", 82))
        semantic_threshold = float(
            (run["configuration"] or {}).get("semantic_threshold", 0.18)
        )
        total_units = max(len(units), 1)
        for unit_index, unit in enumerate(units):
            text_value = unit["text"]
            matches = []
            unit_semantic = semantic_matrix[unit_index] if unit_index < len(semantic_matrix) else []
            for term_index, term_row in enumerate(term_rows):
                semantic_score = (
                    float(unit_semantic[term_index]) if term_index < len(unit_semantic) else 0.0
                )
                matched, score, variant = self._term_match(
                    text_value,
                    term_row,
                    run["search_mode"],
                    threshold,
                    semantic_score,
                    semantic_threshold,
                )
                matches.append(
                    {
                        "term": term_row["term_text"],
                        "matched": matched,
                        "score": score,
                        "variant": variant,
                        "semantic_score": semantic_score,
                    }
                )
            accepted = (
                all(item["matched"] for item in matches)
                if run["logic_operator"] == "AND"
                else any(item["matched"] for item in matches)
            )
            if accepted:
                source_rows = unit["source_rows"]
                block_row = max(
                    source_rows,
                    key=lambda row: max(
                        (
                            partial_ratio(
                                str(term["term_text"]).casefold(),
                                str(row["content_text"] or "").casefold(),
                            )
                            for term in term_rows
                        ),
                        default=0,
                    ),
                )
                document_rows = unit["document_rows"]
                source_index = document_rows.index(block_row)
                result_no += 1
                inserts.append(
                    {
                        "search_run_id": run_id,
                        "result_no": result_no,
                        "document_version_id": block_row["document_version_id"],
                        "page_id": block_row["page_id"],
                        "block_id": block_row["block_id"],
                        "evidence_type": "text",
                        "previous_context": document_rows[source_index - 1]["content_text"]
                        if source_index > 0
                        else None,
                        "matched_context": block_row["content_text"],
                        "next_context": document_rows[source_index + 1]["content_text"]
                        if source_index + 1 < len(document_rows)
                        else None,
                        "matched_terms": matches,
                        "match_details": {
                            "mode": run["search_mode"],
                            "scope": scope,
                            "fuzzy_threshold": threshold,
                            "semantic_threshold": semantic_threshold,
                            "semantic_engine": "local_lsa_v1",
                        },
                        "score": sum(item["score"] for item in matches)
                        / max(len(matches), 1),
                        "bbox": block_row["bbox"],
                        "review_status": "pending",
                        "is_included": True,
                    }
                )
            if unit_index % 200 == 0:
                progress(5 + 90 * (unit_index + 1) / total_units, "searching_blocks")
        if inserts:
            self.db.execute(insert(results), inserts)
        self.db.execute(
            update(runs)
            .where(runs.c.id == run_id)
            .values(status="completed", completed_at=func.now())
        )
        self.db.commit()
        progress(100, "completed")
        return {
            "search_run_id": str(run_id),
            "scanned_blocks": len(rows),
            "result_count": result_no,
        }
