from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    Uuid,
    create_engine,
    select,
)
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Document, DocumentVersion, Organization, Project
from app.schemas.workflow import FieldSchemaFromCandidates
from app.services import term as term_module
from app.services.term import TermService


def _noop_progress(_percent: float, _stage: str) -> None:
    return None


def _field_tables(engine) -> dict[str, Table]:
    metadata = MetaData()
    now = lambda: datetime.now(UTC)  # noqa: E731
    term_categories = Table(
        "term_categories",
        metadata,
        Column("id", Uuid, primary_key=True, default=uuid4),
        Column("project_id", Uuid, nullable=False),
        Column("code", String(100), nullable=False),
        Column("name", String(200), nullable=False),
        Column("description", Text),
        Column("position", Integer, nullable=False, default=0),
        Column("settings", JSON, nullable=False, default=dict),
        Column("created_at", DateTime(timezone=True), default=now),
        Column("updated_at", DateTime(timezone=True), default=now),
    )
    terms = Table(
        "terms",
        metadata,
        Column("id", Uuid, primary_key=True, default=uuid4),
        Column("project_id", Uuid, nullable=False),
        Column("category_id", Uuid),
        Column("canonical_name", Text, nullable=False),
        Column("normalized_name", Text),
        Column("data_type", String(32)),
        Column("semantic_role", String(32)),
        Column("status", String(32), nullable=False, default="candidate"),
        Column("is_selected", Boolean, nullable=False, default=False),
        Column("confidence", Float),
        Column("metadata", JSON, nullable=False, default=dict),
        Column("created_by", Uuid),
        Column("created_at", DateTime(timezone=True), default=now),
        Column("updated_at", DateTime(timezone=True), default=now),
        Column("deleted_at", DateTime(timezone=True)),
    )
    term_aliases = Table(
        "term_aliases",
        metadata,
        Column("id", Uuid, primary_key=True, default=uuid4),
        Column("term_id", Uuid, nullable=False),
        Column("alias_text", Text, nullable=False),
        Column("normalized_alias", Text),
        Column("source", String(50), nullable=False, default="system_suggestion"),
        Column("status", String(32), nullable=False, default="pending"),
        Column("created_by", Uuid),
        Column("created_at", DateTime(timezone=True), default=now),
    )
    document_blocks = Table(
        "document_blocks",
        metadata,
        Column("id", Uuid, primary_key=True, default=uuid4),
        Column("document_version_id", Uuid, nullable=False),
        Column("page_id", Uuid),
        Column("content_text", Text),
    )
    document_tables = Table(
        "document_tables",
        metadata,
        Column("id", Uuid, primary_key=True, default=uuid4),
        Column("document_version_id", Uuid, nullable=False),
        Column("page_id", Uuid),
        Column("title", Text),
        Column("caption", Text),
    )
    document_table_cells = Table(
        "document_table_cells",
        metadata,
        Column("id", Uuid, primary_key=True, default=uuid4),
        Column("table_id", Uuid, nullable=False),
        Column("row_index", Integer),
        Column("column_index", Integer),
        Column("cell_role", String(32)),
        Column("raw_text", Text),
        Column("style", JSON, default=dict),
    )
    document_figures = Table(
        "document_figures",
        metadata,
        Column("id", Uuid, primary_key=True, default=uuid4),
        Column("document_version_id", Uuid, nullable=False),
        Column("page_id", Uuid),
        Column("title", Text),
        Column("caption", Text),
    )
    search_results = Table(
        "search_results",
        metadata,
        Column("id", Uuid, primary_key=True, default=uuid4),
        Column("search_run_id", Uuid, nullable=False),
        Column("is_included", Boolean, nullable=False, default=True),
        Column("block_id", Uuid),
        Column("table_id", Uuid),
        Column("figure_id", Uuid),
    )
    external_calls = Table(
        "external_calls",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("project_id", Uuid, nullable=False),
        Column("job_id", Uuid),
        Column("provider", String(100), nullable=False),
        Column("model_name", String(160)),
        Column("operation", String(100), nullable=False),
        Column("prompt_version", String(100)),
        Column("input_units", Integer),
        Column("output_units", Integer),
        Column("status", String(32), nullable=False),
        Column("error_message", Text),
        Column("metadata", JSON, nullable=False, default=dict),
        Column("created_at", DateTime(timezone=True), default=now),
    )
    field_schemas = Table(
        "field_schemas",
        metadata,
        Column("id", Uuid, primary_key=True, default=uuid4),
        Column("project_id", Uuid, nullable=False),
        Column("version_no", Integer, nullable=False),
        Column("name", String(240), nullable=False),
        Column("status", String(32), nullable=False, default="draft"),
        Column("source_search_run_id", Uuid),
        Column("settings", JSON, nullable=False, default=dict),
        Column("created_by", Uuid),
        Column("created_at", DateTime(timezone=True), default=now),
        Column("updated_at", DateTime(timezone=True), default=now),
        Column("frozen_by", Uuid),
        Column("frozen_at", DateTime(timezone=True)),
    )
    field_definitions = Table(
        "field_definitions",
        metadata,
        Column("id", Uuid, primary_key=True, default=uuid4),
        Column("field_schema_id", Uuid, nullable=False),
        Column("source_term_id", Uuid),
        Column("field_key", String(160), nullable=False),
        Column("display_name", String(240), nullable=False),
        Column("category_code", String(100)),
        Column("semantic_role", String(32), nullable=False, default="feature"),
        Column("data_type", String(32), nullable=False, default="text"),
        Column("preferred_unit_id", Uuid),
        Column("indicator_direction", String(32)),
        Column("is_required", Boolean, nullable=False, default=False),
        Column("is_identifier", Boolean, nullable=False, default=False),
        Column("include_in_model", Boolean, nullable=False, default=False),
        Column("include_in_score", Boolean, nullable=False, default=False),
        Column("position", Integer, nullable=False, default=0),
        Column("extraction_config", JSON, nullable=False, default=dict),
        Column("validation_rules", JSON, nullable=False, default=dict),
        Column("display_config", JSON, nullable=False, default=dict),
        Column("created_at", DateTime(timezone=True), default=now),
    )
    metadata.create_all(engine)
    return {
        "term_categories": term_categories,
        "terms": terms,
        "term_aliases": term_aliases,
        "document_blocks": document_blocks,
        "document_tables": document_tables,
        "document_table_cells": document_table_cells,
        "document_figures": document_figures,
        "search_results": search_results,
        "external_calls": external_calls,
        "field_schemas": field_schemas,
        "field_definitions": field_definitions,
    }


@pytest.fixture
def field_db(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for model in (Organization, Project, Document, DocumentVersion):
        model.__table__.create(engine)  # type: ignore[attr-defined]
    tables = _field_tables(engine)
    monkeypatch.setattr(term_module, "table", lambda _db, name: tables[name])
    with Session(engine) as session:
        yield session, tables


def _project(session: Session) -> UUID:
    organization = Organization(
        id=uuid4(), name="org", slug=f"org-{uuid4().hex[:8]}", settings={}
    )
    session.add(organization)
    project = Project(
        id=uuid4(),
        organization_id=organization.id,
        name="project",
        slug=f"project-{uuid4().hex[:8]}",
        settings={},
    )
    session.add(project)
    session.flush()
    return project.id


def _document_version(session: Session, project_id: UUID, *, version_no: int = 1) -> UUID:
    document = Document(
        id=uuid4(),
        project_id=project_id,
        title="paper",
        authors=[],
        external_identifiers={},
        metadata_json={},
    )
    session.add(document)
    version = DocumentVersion(
        id=uuid4(),
        document_id=document.id,
        version_no=version_no,
        source_file_id=uuid4(),
        parse_status="completed",
        metadata_json={},
    )
    session.add(version)
    session.flush()
    return version.id


def _add_block(session: Session, tables, version_id: UUID, text: str) -> UUID:
    block_id = uuid4()
    session.execute(
        tables["document_blocks"].insert().values(
            id=block_id,
            document_version_id=version_id,
            page_id=uuid4(),
            content_text=text,
        )
    )
    return block_id


def test_discover_fields_finds_numeric_and_header_candidates(field_db) -> None:
    session, tables = field_db
    project_id = _project(session)
    v1 = _document_version(session, project_id)
    v2 = _document_version(session, project_id)
    v3 = _document_version(session, project_id)
    _add_block(session, tables, v1, "本研究中发酵温度为45℃，含水率18%，总糖含量为3.2 g/L。")
    _add_block(session, tables, v2, "发酵温度 42℃ 时风味最佳。")
    _add_block(session, tables, v3, "含水率 20% 的样品口感更好。")
    # 一个带表头的表格
    table_id = uuid4()
    session.execute(
        tables["document_tables"].insert().values(
            id=table_id, document_version_id=v1, page_id=uuid4(), title="表1", caption=""
        )
    )
    session.execute(
        tables["document_table_cells"].insert().values(
            id=uuid4(),
            table_id=table_id,
            row_index=0,
            column_index=0,
            cell_role="header",
            raw_text="感官评分",
            style={},
        )
    )
    session.commit()

    result = TermService(session).discover_fields(
        project_id, _noop_progress, min_documents=1, max_candidates=200, use_llm=False
    )

    assert result["used_llm"] is False
    assert result["created_count"] >= 3
    assert result["numeric_count"] >= 2

    candidates = TermService(session).list_field_candidates(project_id)
    by_name = {item["display_name"]: item for item in candidates}

    assert "发酵温度" in by_name
    temp = by_name["发酵温度"]
    assert temp["document_count"] == 2
    assert temp["data_type"] == "number"
    assert temp["suggested_unit"] == "℃"

    assert "含水率" in by_name
    assert by_name["含水率"]["document_count"] == 2
    assert by_name["含水率"]["suggested_unit"] == "%"

    assert "感官评分" in by_name  # 来自表头候选


def test_discover_fields_collects_aliases(field_db) -> None:
    session, tables = field_db
    project_id = _project(session)
    v1 = _document_version(session, project_id)
    _add_block(session, tables, v1, "含水率18%。含水率 为 22 %。")
    session.commit()

    TermService(session).discover_fields(
        project_id, _noop_progress, min_documents=1, use_llm=False
    )

    candidates = TermService(session).list_field_candidates(project_id)
    water = next(item for item in candidates if item["display_name"] == "含水率")
    normalized_aliases = {alias.strip() for alias in water["aliases"]}
    assert "含水率" in normalized_aliases


def test_list_field_candidates_shape_and_sorting(field_db) -> None:
    session, tables = field_db
    project_id = _project(session)
    v1 = _document_version(session, project_id)
    v2 = _document_version(session, project_id)
    _add_block(session, tables, v1, "发酵温度为45℃，含水率18%。")
    _add_block(session, tables, v2, "发酵温度 42℃。")
    session.commit()

    TermService(session).discover_fields(
        project_id, _noop_progress, min_documents=1, use_llm=False
    )
    candidates = TermService(session).list_field_candidates(project_id)

    assert candidates
    expected_keys = {
        "id",
        "display_name",
        "category",
        "category_id",
        "data_type",
        "suggested_role",
        "suggested_unit",
        "occurrence_count",
        "document_count",
        "confidence",
        "examples",
        "aliases",
    }
    assert expected_keys <= set(candidates[0])
    document_counts = [item["document_count"] for item in candidates]
    assert document_counts == sorted(document_counts, reverse=True)
    # 发酵温度 出现在两篇文档，应排在最前
    assert candidates[0]["display_name"] == "发酵温度"
    assert isinstance(candidates[0]["examples"], list)


def test_create_field_schema_from_candidates(field_db) -> None:
    session, tables = field_db
    project_id = _project(session)
    v1 = _document_version(session, project_id)
    v2 = _document_version(session, project_id)
    _add_block(session, tables, v1, "发酵温度为45℃，含水率18%。")
    _add_block(session, tables, v2, "发酵温度 42℃，含水率 20%。")
    session.commit()

    TermService(session).discover_fields(
        project_id, _noop_progress, min_documents=1, use_llm=False
    )
    candidates = TermService(session).list_field_candidates(project_id)
    temp = next(item for item in candidates if item["display_name"] == "发酵温度")
    water = next(item for item in candidates if item["display_name"] == "含水率")

    payload = FieldSchemaFromCandidates(
        name="发酵字段方案",
        candidates=[
            {
                "term_id": temp["id"],
                "field_key": "fermentation_temp",
                "display_name": "发酵温度",
                "data_type": "number",
            },
            {
                "term_id": water["id"],
                "field_key": "water_content",
                "display_name": "含水率",
                "data_type": "number",
            },
        ],
    )
    schema = TermService(session).create_field_schema_from_candidates(
        project_id, payload, actor_id=None
    )

    assert schema["name"] == "发酵字段方案"
    fields = {field["field_key"]: field for field in schema["fields"]}
    assert set(fields) == {"fermentation_temp", "water_content"}
    temp_field = fields["fermentation_temp"]
    assert temp_field["source_term_id"] == temp["id"]
    assert "发酵温度" in temp_field["extraction_config"]["aliases"]

    # 对应术语应被置为已确认并选中
    terms = tables["terms"]
    status_row = session.execute(
        select(terms.c.status, terms.c.is_selected).where(terms.c.id == temp["id"])
    ).mappings().one()
    assert status_row["status"] == "confirmed"
    assert status_row["is_selected"] is True


def test_create_field_schema_from_candidates_rejects_foreign_term(field_db) -> None:
    session, tables = field_db
    project_id = _project(session)
    other_project = _project(session)
    v1 = _document_version(session, project_id)
    _add_block(session, tables, v1, "发酵温度为45℃。")
    session.commit()

    TermService(session).discover_fields(
        project_id, _noop_progress, min_documents=1, use_llm=False
    )
    candidates = TermService(session).list_field_candidates(project_id)
    term_id = candidates[0]["id"]

    payload = FieldSchemaFromCandidates(
        name="错误方案",
        candidates=[
            {
                "term_id": term_id,
                "field_key": "temp",
                "display_name": "发酵温度",
            }
        ],
    )
    from app.core.errors import AppError

    with pytest.raises(AppError, match="不属于当前项目"):
        TermService(session).create_field_schema_from_candidates(
            other_project, payload, actor_id=None
        )


def test_discover_fields_respects_search_run_scope(field_db) -> None:
    session, tables = field_db
    project_id = _project(session)
    v1 = _document_version(session, project_id)
    included = _add_block(session, tables, v1, "发酵温度为45℃。")
    _add_block(session, tables, v1, "含水率18%。")
    search_run_id = uuid4()
    session.execute(
        tables["search_results"].insert().values(
            id=uuid4(),
            search_run_id=search_run_id,
            is_included=True,
            block_id=included,
        )
    )
    session.commit()

    result = TermService(session).discover_fields(
        project_id,
        _noop_progress,
        search_run_id=search_run_id,
        min_documents=1,
        use_llm=False,
    )

    candidates = TermService(session).list_field_candidates(project_id)
    names = {item["display_name"] for item in candidates}
    assert "发酵温度" in names
    assert "含水率" not in names
    assert result["candidate_count"] >= 1


def test_discover_fields_use_llm_true_without_key_falls_back(field_db, monkeypatch) -> None:
    session, tables = field_db
    project_id = _project(session)
    v1 = _document_version(session, project_id)
    _add_block(session, tables, v1, "发酵温度为45℃。")
    session.commit()

    # 确保没有 deepseek key 时，use_llm=True 也不会联网，退化为纯规则
    class _FakeSecret:
        @staticmethod
        def get_secret_value() -> str:
            return ""

    class _FakeSettings:
        deepseek_api_key = _FakeSecret()
        deepseek_base_url = "https://api.deepseek.com"
        deepseek_model = "deepseek-chat"

    monkeypatch.setattr(term_module, "get_settings", lambda: _FakeSettings())

    def _boom(*_args: Any, **_kwargs: Any):  # pragma: no cover - 不应被调用
        raise AssertionError("网络调用不应发生")

    monkeypatch.setattr(term_module.httpx, "Client", _boom)

    result = TermService(session).discover_fields(
        project_id, _noop_progress, min_documents=1, use_llm=True
    )

    assert result["used_llm"] is False
    assert result["created_count"] >= 1
