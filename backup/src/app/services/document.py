import io
import zipfile
from pathlib import Path, PurePosixPath
from uuid import UUID

import fitz
from fastapi import UploadFile
from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.tables import table
from app.models import Document, DocumentVersion, ProcessingJob, Project, StoredFile
from app.schemas.document import DocumentResponse, UploadBatchResponse, UploadResult
from app.services.storage import LocalStorage, SavedUpload


class DocumentService:
    def __init__(self, db: Session, storage: LocalStorage) -> None:
        self.db = db
        self.storage = storage

    def _project(self, project_id: UUID) -> Project:
        project = self.db.scalar(
            select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
        )
        if not project:
            raise AppError(code="project_not_found", message="项目不存在", status_code=404)
        return project

    def _archive_uploads(self, saved: SavedUpload) -> list[UploadFile]:
        if saved.extension != "zip":
            return []
        uploads: list[UploadFile] = []
        total_uncompressed = 0
        maximum_bytes = self.storage.settings.zip_max_uncompressed_mb * 1024 * 1024
        with zipfile.ZipFile(saved.path) as archive:
            entries = [item for item in archive.infolist() if not item.is_dir()]
            if len(entries) > self.storage.settings.zip_max_entries:
                raise AppError(
                    code="zip_too_many_entries", message="ZIP 文件数量超过限制", status_code=413
                )
            for entry in entries:
                normalized = PurePosixPath(entry.filename.replace("\\", "/"))
                if normalized.is_absolute() or ".." in normalized.parts:
                    raise AppError(
                        code="unsafe_zip_path", message="ZIP 包含不安全路径", status_code=400
                    )
                if entry.flag_bits & 0x1:
                    raise AppError(
                        code="encrypted_zip_entry", message="不支持加密 ZIP 文件", status_code=422
                    )
                total_uncompressed += entry.file_size
                if total_uncompressed > maximum_bytes:
                    raise AppError(
                        code="zip_too_large", message="ZIP 解压后大小超过限制", status_code=413
                    )
                ratio = entry.file_size / max(entry.compress_size, 1)
                if ratio > self.storage.settings.zip_max_compression_ratio:
                    raise AppError(
                        code="zip_bomb_detected", message="ZIP 压缩比异常", status_code=400
                    )
                extension = normalized.suffix.lower().lstrip(".")
                if extension == "zip":
                    raise AppError(
                        code="nested_zip_not_allowed", message="不支持嵌套 ZIP", status_code=422
                    )
                if extension not in self.storage.settings.allowed_extension_set:
                    continue
                content = archive.read(entry)
                self.storage._validate_signature(extension, content[:16])
                uploads.append(UploadFile(file=io.BytesIO(content), filename=normalized.name))
        return uploads

    def upload_many(
        self,
        *,
        project_id: UUID,
        files: list[UploadFile],
        actor_id: UUID | None,
    ) -> UploadBatchResponse:
        project = self._project(project_id)
        if not files:
            raise AppError(code="files_required", message="至少需要上传一个文件", status_code=400)

        results: list[UploadResult] = []
        archive_children: list[UploadFile] = []
        for upload in files:
            saved: SavedUpload | None = None
            current_archive_children: list[UploadFile] = []
            filename = upload.filename or "unnamed"
            try:
                saved = self.storage.save(project_id, upload)
                current_archive_children = self._archive_uploads(saved)
                duplicate = self.db.scalar(
                    select(StoredFile).where(
                        StoredFile.project_id == project_id,
                        StoredFile.sha256 == saved.sha256,
                        StoredFile.deleted_at.is_(None),
                    )
                )
                if duplicate:
                    self.storage.remove(saved)
                    results.append(
                        UploadResult(
                            filename=filename,
                            status="duplicate",
                            message="项目中已存在内容相同的文件",
                            duplicate_file_id=duplicate.id,
                        )
                    )
                    continue

                stored_file = StoredFile(
                    organization_id=project.organization_id,
                    project_id=project.id,
                    storage_provider="local",
                    storage_key=saved.storage_key,
                    original_name=filename,
                    safe_name=saved.safe_name,
                    extension=saved.extension,
                    media_type=saved.media_type,
                    byte_size=saved.byte_size,
                    sha256=saved.sha256,
                    purpose="upload",
                    security_status="passed",
                    metadata_json={},
                    created_by=actor_id,
                )
                self.db.add(stored_file)
                self.db.flush()

                existing = self.db.execute(
                    select(Document, DocumentVersion.version_no)
                    .join(DocumentVersion, DocumentVersion.document_id == Document.id)
                    .join(StoredFile, StoredFile.id == DocumentVersion.source_file_id)
                    .where(
                        Document.project_id == project_id,
                        Document.deleted_at.is_(None),
                        func.lower(StoredFile.original_name) == filename.casefold(),
                    )
                    .order_by(DocumentVersion.version_no.desc())
                    .limit(1)
                ).one_or_none()
                if existing:
                    document, latest_version = existing
                    version_no = latest_version + 1
                else:
                    document = Document(
                        project_id=project.id,
                        document_type="paper",
                        title=Path(filename).stem,
                        authors=[],
                        external_identifiers={},
                        metadata_json={},
                        created_by=actor_id,
                    )
                    self.db.add(document)
                    self.db.flush()
                    version_no = 1

                version = DocumentVersion(
                    document_id=document.id,
                    version_no=version_no,
                    source_file_id=stored_file.id,
                    source_kind="upload",
                    parse_status="pending",
                    metadata_json={},
                    created_by=actor_id,
                )
                self.db.add(version)
                self.db.flush()

                job = ProcessingJob(
                    project_id=project.id,
                    document_version_id=version.id,
                    job_type="parse_document",
                    status="queued",
                    progress_percent=0,
                    current_stage="waiting",
                    idempotency_key=f"parse_document:{version.id}",
                    requested_config={},
                    result_summary={},
                    requested_by=actor_id,
                )
                self.db.add(job)
                self.db.commit()
                archive_children.extend(current_archive_children)
                results.append(
                    UploadResult(
                        filename=filename,
                        status="created",
                        file_id=stored_file.id,
                        document_id=document.id,
                        document_version_id=version.id,
                        job_id=job.id,
                    )
                )
            except AppError as exc:
                self.db.rollback()
                if saved:
                    self.storage.remove(saved)
                results.append(
                    UploadResult(filename=filename, status="failed", message=exc.message)
                )
            except SQLAlchemyError:
                self.db.rollback()
                if saved:
                    self.storage.remove(saved)
                results.append(
                    UploadResult(filename=filename, status="failed", message="数据库写入失败")
                )
            finally:
                upload.file.close()

        if archive_children:
            child_result = self.upload_many(
                project_id=project_id,
                files=archive_children,
                actor_id=actor_id,
            )
            results.extend(child_result.items)

        succeeded = sum(item.status == "created" for item in results)
        duplicated = sum(item.status == "duplicate" for item in results)
        failed = sum(item.status == "failed" for item in results)
        return UploadBatchResponse(
            project_id=project_id,
            total=len(results),
            succeeded=succeeded,
            duplicated=duplicated,
            failed=failed,
            items=results,
        )

    def list(
        self,
        *,
        project_id: UUID,
        offset: int,
        limit: int,
    ) -> tuple[list[DocumentResponse], int]:
        self._project(project_id)
        filters = [Document.project_id == project_id, Document.deleted_at.is_(None)]
        total = self.db.scalar(select(func.count()).select_from(Document).where(*filters)) or 0
        latest = (
            select(
                DocumentVersion.document_id,
                func.max(DocumentVersion.version_no).label("version_no"),
            )
            .group_by(DocumentVersion.document_id)
            .subquery()
        )
        rows = self.db.execute(
            select(Document, DocumentVersion, StoredFile)
            .join(latest, latest.c.document_id == Document.id)
            .join(
                DocumentVersion,
                (DocumentVersion.document_id == latest.c.document_id)
                & (DocumentVersion.version_no == latest.c.version_no),
            )
            .join(StoredFile, StoredFile.id == DocumentVersion.source_file_id)
            .where(*filters)
            .order_by(Document.created_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return [
            DocumentResponse(
                id=document.id,
                project_id=document.project_id,
                title=document.title,
                document_type=document.document_type,
                language=document.language,
                status=document.status,
                version_id=version.id,
                version_no=version.version_no,
                parse_status=version.parse_status,
                page_count=version.page_count,
                original_name=stored_file.original_name,
                byte_size=stored_file.byte_size,
                created_at=document.created_at,
            )
            for document, version, stored_file in rows
        ], total

    def detail(self, project_id: UUID, document_id: UUID) -> dict:
        document = self.db.scalar(
            select(Document).where(
                Document.id == document_id,
                Document.project_id == project_id,
                Document.deleted_at.is_(None),
            )
        )
        if not document:
            raise AppError(code="document_not_found", message="文献不存在", status_code=404)
        version = self.db.scalar(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_no.desc())
            .limit(1)
        )
        if not version:
            raise AppError(
                code="document_version_not_found", message="文献版本不存在", status_code=404
            )
        source_file = self.db.get(StoredFile, version.source_file_id)
        pages = table(self.db, "document_pages")
        blocks = table(self.db, "document_blocks")
        tables_table = table(self.db, "document_tables")
        cells = table(self.db, "document_table_cells")
        figures = table(self.db, "document_figures")
        page_rows = [
            dict(row)
            for row in self.db.execute(
                select(pages)
                .where(pages.c.document_version_id == version.id)
                .order_by(pages.c.page_no)
            ).mappings()
        ]
        page_no_by_id: dict[UUID, int] = {}
        for page_row in page_rows:
            page_row["width"] = float(page_row["width"]) if page_row["width"] is not None else None
            page_row["height"] = (
                float(page_row["height"]) if page_row["height"] is not None else None
            )
            page_row["has_image"] = page_row.get("rendered_image_file_id") is not None
            page_no_by_id[page_row["id"]] = page_row["page_no"]
        block_rows = [
            dict(row)
            for row in self.db.execute(
                select(blocks)
                .where(blocks.c.document_version_id == version.id)
                .order_by(blocks.c.page_id, blocks.c.sequence_no)
            ).mappings()
        ]
        table_rows = [
            dict(row)
            for row in self.db.execute(
                select(tables_table)
                .where(tables_table.c.document_version_id == version.id)
                .order_by(tables_table.c.page_id, tables_table.c.table_no)
            ).mappings()
        ]
        table_ids = [row["id"] for row in table_rows]
        cell_rows = (
            [
                dict(row)
                for row in self.db.execute(
                    select(cells)
                    .where(cells.c.table_id.in_(table_ids))
                    .order_by(
                        cells.c.table_id,
                        cells.c.row_index,
                        cells.c.column_index,
                    )
                ).mappings()
            ]
            if table_ids
            else []
        )
        cells_by_table: dict[UUID, list[dict]] = {}
        for cell in cell_rows:
            cells_by_table.setdefault(cell["table_id"], []).append(cell)
        for table_row in table_rows:
            table_row["cells"] = cells_by_table.get(table_row["id"], [])
        figure_rows = [
            dict(row)
            for row in self.db.execute(
                select(figures)
                .where(figures.c.document_version_id == version.id)
                .order_by(figures.c.page_id, figures.c.figure_no)
            ).mappings()
        ]
        for row_item in [*block_rows, *table_rows, *figure_rows]:
            row_item["page_no"] = page_no_by_id.get(row_item["page_id"])
        return {
            "document": {
                "id": document.id,
                "project_id": document.project_id,
                "title": document.title,
                "authors": document.authors,
                "publication_year": document.publication_year,
                "publication_name": document.publication_name,
                "doi": document.doi,
                "language": document.language,
                "status": document.status,
            },
            "version": {
                "id": version.id,
                "version_no": version.version_no,
                "parse_status": version.parse_status,
                "page_count": version.page_count,
                "original_name": source_file.original_name if source_file else None,
                "byte_size": source_file.byte_size if source_file else None,
                "media_type": source_file.media_type if source_file else None,
                "metadata": version.metadata_json,
            },
            "pages": page_rows,
            "blocks": block_rows,
            "tables": table_rows,
            "figures": figure_rows,
            "counts": {
                "blocks": self.db.scalar(
                    select(func.count())
                    .select_from(blocks)
                    .where(blocks.c.document_version_id == version.id)
                )
                or 0,
                "tables": self.db.scalar(
                    select(func.count())
                    .select_from(tables_table)
                    .where(tables_table.c.document_version_id == version.id)
                )
                or 0,
                "figures": self.db.scalar(
                    select(func.count())
                    .select_from(figures)
                    .where(figures.c.document_version_id == version.id)
                )
                or 0,
            },
        }

    def source_path(self, project_id: UUID, document_id: UUID) -> tuple[Path, str, str | None]:
        row = self.db.execute(
            select(Document, DocumentVersion, StoredFile)
            .join(DocumentVersion, DocumentVersion.document_id == Document.id)
            .join(StoredFile, StoredFile.id == DocumentVersion.source_file_id)
            .where(Document.id == document_id, Document.project_id == project_id)
            .order_by(DocumentVersion.version_no.desc())
            .limit(1)
        ).one_or_none()
        if not row:
            raise AppError(code="document_not_found", message="文献不存在", status_code=404)
        _, _, stored = row
        return (
            self.storage.path_for_key(stored.storage_key),
            stored.original_name,
            stored.media_type,
        )

    def figure_path(
        self, project_id: UUID, document_id: UUID, figure_id: UUID
    ) -> tuple[Path, str, str | None]:
        figures = table(self.db, "document_figures")
        row = self.db.execute(
            select(figures.c.figure_no, StoredFile)
            .join(DocumentVersion, DocumentVersion.id == figures.c.document_version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .join(StoredFile, StoredFile.id == figures.c.image_file_id)
            .where(
                figures.c.id == figure_id,
                Document.id == document_id,
                Document.project_id == project_id,
                Document.deleted_at.is_(None),
                StoredFile.deleted_at.is_(None),
            )
        ).one_or_none()
        if not row:
            raise AppError(code="figure_not_found", message="文献图片不存在", status_code=404)
        figure_no, stored = row
        return (
            self.storage.path_for_key(stored.storage_key),
            f"{figure_no}.{stored.extension or 'png'}",
            stored.media_type,
        )

    def page_image_path(
        self, project_id: UUID, document_id: UUID, page_no: int
    ) -> tuple[Path, str, str]:
        project = self._project(project_id)
        row = self.db.execute(
            select(DocumentVersion, StoredFile)
            .join(Document, Document.id == DocumentVersion.document_id)
            .join(StoredFile, StoredFile.id == DocumentVersion.source_file_id)
            .where(
                Document.id == document_id,
                Document.project_id == project_id,
                Document.deleted_at.is_(None),
            )
            .order_by(DocumentVersion.version_no.desc())
            .limit(1)
        ).one_or_none()
        if not row:
            raise AppError(code="document_not_found", message="文献不存在", status_code=404)
        version, source_file = row
        pages = table(self.db, "document_pages")
        page_row = (
            self.db.execute(
                select(pages).where(
                    pages.c.document_version_id == version.id,
                    pages.c.page_no == page_no,
                )
            )
            .mappings()
            .one_or_none()
        )
        if not page_row:
            raise AppError(code="page_not_found", message="文献页不存在", status_code=404)

        rendered_file_id = page_row["rendered_image_file_id"]
        if rendered_file_id:
            rendered = self.db.get(StoredFile, rendered_file_id)
            if rendered and rendered.deleted_at is None:
                path = self.storage.path_for_key(rendered.storage_key)
                if path.exists():
                    return (
                        path,
                        f"page-{page_no}.{rendered.extension or 'png'}",
                        rendered.media_type or "image/png",
                    )

        if (source_file.extension or "").lower() != "pdf":
            raise AppError(
                code="page_image_unavailable",
                message="仅 PDF 文献支持页面图像渲染",
                status_code=404,
            )
        source_path = self.storage.path_for_key(source_file.storage_key)
        if not source_path.exists():
            raise AppError(code="source_file_missing", message="原始文件不存在", status_code=409)

        pdf = fitz.open(source_path)
        try:
            if page_no > len(pdf):
                raise AppError(code="page_not_found", message="文献页不存在", status_code=404)
            page = pdf[page_no - 1]
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=False)
            content = pixmap.tobytes("png")
            page_width = round(float(page.rect.width), 3)
            page_height = round(float(page.rect.height), 3)
        finally:
            pdf.close()

        saved = self.storage.save_bytes(
            project_id,
            category="pages",
            extension="png",
            content=content,
            media_type="image/png",
        )
        stored = StoredFile(
            organization_id=project.organization_id,
            project_id=project.id,
            storage_provider="local",
            storage_key=saved.storage_key,
            original_name=f"page-{page_no}.png",
            safe_name=saved.safe_name,
            extension="png",
            media_type="image/png",
            byte_size=saved.byte_size,
            sha256=saved.sha256,
            purpose="page_render",
            security_status="generated",
            metadata_json={
                "document_version_id": str(version.id),
                "page_no": page_no,
                "zoom": 2.0,
            },
        )
        self.db.add(stored)
        self.db.flush()
        self.db.execute(
            update(pages)
            .where(pages.c.id == page_row["id"])
            .values(
                rendered_image_file_id=stored.id,
                width=page_width,
                height=page_height,
            )
        )
        self.db.commit()
        return saved.path, f"page-{page_no}.png", "image/png"

    def enqueue_reparse(
        self, project_id: UUID, document_id: UUID, actor_id: UUID | None
    ) -> ProcessingJob:
        version = self.db.scalar(
            select(DocumentVersion)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(Document.id == document_id, Document.project_id == project_id)
            .order_by(DocumentVersion.version_no.desc())
            .limit(1)
        )
        if not version:
            raise AppError(code="document_not_found", message="文献不存在", status_code=404)
        job = ProcessingJob(
            project_id=project_id,
            document_version_id=version.id,
            job_type="parse_document",
            status="queued",
            progress_percent=0,
            current_stage="waiting",
            requested_config={"force": True},
            result_summary={},
            requested_by=actor_id,
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job
