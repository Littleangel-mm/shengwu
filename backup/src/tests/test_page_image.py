from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import fitz
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import (
    JSON,
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
    event,
    func,
    select,
)
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import deps
from app.api.deps import require_project_access
from app.api.v1 import documents as documents_module
from app.core.config import Settings
from app.main import app
from app.models import Document, DocumentVersion, Organization, Project, StoredFile
from app.services import document as document_module
from app.services.document import DocumentService
from app.services.storage import LocalStorage


def _document_tables(engine) -> dict[str, Table]:
    metadata = MetaData()
    now = lambda: datetime.now(UTC)  # noqa: E731
    document_pages = Table(
        "document_pages",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("document_version_id", Uuid, nullable=False),
        Column("page_no", Integer, nullable=False),
        Column("width", Float),
        Column("height", Float),
        Column("rotation", Integer, nullable=False, default=0),
        Column("text_content", Text),
        Column("text_source", String(32)),
        Column("ocr_confidence", Float),
        Column("rendered_image_file_id", Uuid),
        Column("metadata", JSON, nullable=False, default=dict),
        Column("created_at", DateTime(timezone=True), nullable=False, default=now),
    )
    document_blocks = Table(
        "document_blocks",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("document_version_id", Uuid, nullable=False),
        Column("page_id", Uuid),
        Column("block_type", String(50)),
        Column("sequence_no", Integer),
        Column("section_path", JSON, default=list),
        Column("content_text", Text),
        Column("bbox", JSON),
        Column("style", JSON, default=dict),
        Column("parser_payload", JSON, default=dict),
        Column("confidence", Float),
    )
    document_tables = Table(
        "document_tables",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("document_version_id", Uuid, nullable=False),
        Column("page_id", Uuid),
        Column("table_no", String(100)),
        Column("title", Text),
        Column("caption", Text),
        Column("row_count", Integer),
        Column("column_count", Integer),
        Column("bbox", JSON),
        Column("structured_data", JSON, default=dict),
        Column("confidence", Float),
    )
    document_table_cells = Table(
        "document_table_cells",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("table_id", Uuid, nullable=False),
        Column("row_index", Integer),
        Column("column_index", Integer),
        Column("raw_text", Text),
        Column("normalized_text", Text),
        Column("bbox", JSON),
        Column("style", JSON, default=dict),
        Column("confidence", Float),
    )
    document_figures = Table(
        "document_figures",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("document_version_id", Uuid, nullable=False),
        Column("page_id", Uuid),
        Column("figure_no", String(100)),
        Column("title", Text),
        Column("caption", Text),
        Column("figure_type", String(50)),
        Column("bbox", JSON),
        Column("image_file_id", Uuid),
        Column("axis_metadata", JSON, default=dict),
        Column("legend_metadata", JSON, default=dict),
        Column("extracted_labels", JSON, default=list),
        Column("semantic_summary", Text),
        Column("confidence", Float),
    )
    metadata.create_all(engine)
    return {
        "document_pages": document_pages,
        "document_blocks": document_blocks,
        "document_tables": document_tables,
        "document_table_cells": document_table_cells,
        "document_figures": document_figures,
    }


def _single_page_pdf_bytes(text: str) -> bytes:
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_text((72, 72), text)
    content = pdf.tobytes()
    pdf.close()
    return content


def _assign_stored_file_id(_mapper: Any, _connection: Any, target: StoredFile) -> None:
    if target.id is None:
        target.id = uuid4()


@pytest.fixture
def page_image_env(monkeypatch, tmp_path: Path):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for model in (Organization, Project, StoredFile, Document, DocumentVersion):
        model.__table__.create(engine)  # type: ignore[attr-defined]
    tables = _document_tables(engine)
    monkeypatch.setattr(document_module, "table", lambda _db, name: tables[name])
    settings = Settings(storage_root=tmp_path / "storage")
    monkeypatch.setattr(documents_module, "get_settings", lambda: settings)
    event.listen(StoredFile, "before_insert", _assign_stored_file_id)
    session = Session(engine)
    app.dependency_overrides[deps.get_db] = lambda: session
    app.dependency_overrides[require_project_access] = lambda: uuid4()
    try:
        yield session, tables, settings
    finally:
        app.dependency_overrides.pop(deps.get_db, None)
        app.dependency_overrides.pop(require_project_access, None)
        event.remove(StoredFile, "before_insert", _assign_stored_file_id)
        session.close()


def _create_document(
    session: Session,
    tables: dict[str, Table],
    storage: LocalStorage,
    *,
    content: bytes,
    extension: str,
) -> tuple[UUID, UUID, UUID]:
    organization = Organization(id=uuid4(), name="org", slug=f"org-{uuid4().hex[:8]}", settings={})
    session.add(organization)
    project = Project(
        id=uuid4(),
        organization_id=organization.id,
        name="project",
        slug=f"project-{uuid4().hex[:8]}",
        settings={},
    )
    session.add(project)
    saved = storage.save_bytes(
        project.id, category="uploads", extension=extension, content=content
    )
    source = StoredFile(
        id=uuid4(),
        organization_id=organization.id,
        project_id=project.id,
        storage_provider="local",
        storage_key=saved.storage_key,
        original_name=f"paper.{extension}",
        safe_name=saved.safe_name,
        extension=extension,
        media_type=saved.media_type,
        byte_size=saved.byte_size,
        sha256=saved.sha256,
        purpose="upload",
        security_status="passed",
        metadata_json={},
    )
    session.add(source)
    document = Document(
        id=uuid4(),
        project_id=project.id,
        title="paper",
        authors=[],
        external_identifiers={},
        metadata_json={},
    )
    session.add(document)
    version = DocumentVersion(
        id=uuid4(),
        document_id=document.id,
        version_no=1,
        source_file_id=source.id,
        parse_status="completed",
        metadata_json={},
    )
    session.add(version)
    session.flush()
    page_id = uuid4()
    session.execute(
        tables["document_pages"]
        .insert()
        .values(
            id=page_id,
            document_version_id=version.id,
            page_no=1,
            text_content="Hello evidence",
            text_source="embedded",
            metadata={},
        )
    )
    session.commit()
    return project.id, document.id, page_id


def test_page_image_endpoint_renders_then_caches(page_image_env) -> None:
    session, tables, settings = page_image_env
    storage = LocalStorage(settings)
    project_id, document_id, page_id = _create_document(
        session,
        tables,
        storage,
        content=_single_page_pdf_bytes("Hello evidence"),
        extension="pdf",
    )
    client = TestClient(app)
    url = f"/api/v1/projects/{project_id}/documents/{document_id}/pages/1/image"

    first = client.get(url)
    assert first.status_code == 200, first.text
    assert first.content.startswith(b"\x89PNG")

    pages = tables["document_pages"]
    page_row = session.execute(select(pages).where(pages.c.id == page_id)).mappings().one()
    assert page_row["rendered_image_file_id"] is not None
    assert page_row["width"] == pytest.approx(595, abs=1)
    assert page_row["height"] == pytest.approx(842, abs=1)
    rendered = session.get(StoredFile, page_row["rendered_image_file_id"])
    assert rendered is not None and rendered.purpose == "page_render"
    render_count = session.scalar(
        select(func.count()).select_from(StoredFile.__table__).where(
            StoredFile.purpose == "page_render"
        )
    )
    assert render_count == 1

    second = client.get(url)
    assert second.status_code == 200
    assert second.content == first.content
    session.expire_all()
    cached_row = session.execute(select(pages).where(pages.c.id == page_id)).mappings().one()
    assert cached_row["rendered_image_file_id"] == page_row["rendered_image_file_id"]
    render_count_after = session.scalar(
        select(func.count()).select_from(StoredFile.__table__).where(
            StoredFile.purpose == "page_render"
        )
    )
    assert render_count_after == 1

    missing = client.get(f"/api/v1/projects/{project_id}/documents/{document_id}/pages/99/image")
    assert missing.status_code == 404


def test_page_image_endpoint_returns_404_for_non_pdf(page_image_env) -> None:
    session, tables, settings = page_image_env
    storage = LocalStorage(settings)
    project_id, document_id, _ = _create_document(
        session,
        tables,
        storage,
        content=b"plain text source",
        extension="txt",
    )
    client = TestClient(app)
    response = client.get(
        f"/api/v1/projects/{project_id}/documents/{document_id}/pages/1/image"
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "page_image_unavailable"


def test_detail_pages_include_dimensions_and_image_flag(page_image_env) -> None:
    session, tables, settings = page_image_env
    storage = LocalStorage(settings)
    project_id, document_id, page_id = _create_document(
        session,
        tables,
        storage,
        content=_single_page_pdf_bytes("Hello evidence"),
        extension="pdf",
    )
    version_id = session.scalar(
        select(DocumentVersion.id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(Document.id == document_id)
    )
    session.execute(
        tables["document_blocks"]
        .insert()
        .values(
            id=uuid4(),
            document_version_id=version_id,
            page_id=page_id,
            block_type="paragraph",
            sequence_no=0,
            section_path=[],
            content_text="Hello evidence",
            bbox=[72.0, 60.0, 300.0, 80.0],
            style={},
            parser_payload={},
        )
    )
    session.commit()

    service = DocumentService(session, storage)
    before = service.detail(project_id, document_id)
    assert before["pages"][0]["page_no"] == 1
    assert before["pages"][0]["has_image"] is False
    assert before["blocks"][0]["page_no"] == 1
    assert before["blocks"][0]["bbox"] == [72.0, 60.0, 300.0, 80.0]

    path, filename, media_type = service.page_image_path(project_id, document_id, 1)
    assert path.exists() and filename == "page-1.png" and media_type == "image/png"

    after = service.detail(project_id, document_id)
    page = after["pages"][0]
    assert page["has_image"] is True
    assert page["width"] == pytest.approx(595, abs=1)
    assert page["height"] == pytest.approx(842, abs=1)
