import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

from fastapi import UploadFile

from app.core.config import Settings
from app.core.errors import AppError


@dataclass(frozen=True)
class SavedUpload:
    storage_key: str
    path: Path
    safe_name: str
    extension: str
    media_type: str | None
    byte_size: int
    sha256: str


class LocalStorage:
    chunk_size = 1024 * 1024

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = settings.storage_root.resolve()

    def ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for_key(self, storage_key: str) -> Path:
        relative = PurePosixPath(storage_key)
        if relative.is_absolute() or ".." in relative.parts:
            raise AppError(code="invalid_storage_key", message="文件存储标识无效", status_code=400)
        path = (self.root / Path(*relative.parts)).resolve()
        if self.root != path and self.root not in path.parents:
            raise AppError(code="invalid_storage_path", message="文件存储路径无效", status_code=400)
        return path

    def save_bytes(
        self,
        project_id: UUID,
        *,
        category: str,
        extension: str,
        content: bytes,
        media_type: str | None = None,
    ) -> SavedUpload:
        self.ensure_root()
        extension = extension.lower().lstrip(".")
        now = datetime.now(UTC)
        safe_name = f"{uuid4().hex}.{extension}"
        relative = PurePosixPath(category) / str(project_id) / f"{now:%Y}" / f"{now:%m}" / safe_name
        destination = self.path_for_key(relative.as_posix())
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return SavedUpload(
            storage_key=relative.as_posix(),
            path=destination,
            safe_name=safe_name,
            extension=extension,
            media_type=media_type,
            byte_size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )

    def _extension(self, filename: str | None) -> str:
        extension = Path(filename or "").suffix.lower().lstrip(".")
        if extension not in self.settings.allowed_extension_set:
            raise AppError(
                code="unsupported_file_type",
                message=f"不支持的文件类型：{extension or '无扩展名'}",
                status_code=415,
            )
        return extension

    @staticmethod
    def _validate_signature(extension: str, head: bytes) -> None:
        if extension == "pdf" and not head.startswith(b"%PDF-"):
            raise AppError(code="invalid_file_signature", message="PDF 文件头无效", status_code=415)
        if extension in {"docx", "xlsx", "zip"} and not head.startswith(b"PK"):
            raise AppError(
                code="invalid_file_signature", message="压缩文档文件头无效", status_code=415
            )
        if extension == "xls" and not head.startswith(bytes.fromhex("D0CF11E0")):
            raise AppError(code="invalid_file_signature", message="XLS 文件头无效", status_code=415)
        if extension in {"txt", "md", "csv"} and b"\x00" in head:
            raise AppError(
                code="invalid_text_file", message="文本文件包含二进制内容", status_code=415
            )

    def save(self, project_id: UUID, upload: UploadFile) -> SavedUpload:
        self.ensure_root()
        extension = self._extension(upload.filename)
        now = datetime.now(UTC)
        safe_name = f"{uuid4().hex}.{extension}"
        relative = (
            PurePosixPath("uploads") / str(project_id) / f"{now:%Y}" / f"{now:%m}" / safe_name
        )
        destination = self.path_for_key(relative.as_posix())
        destination.parent.mkdir(parents=True, exist_ok=True)

        digest = hashlib.sha256()
        total = 0
        head = b""
        try:
            with destination.open("xb") as output:
                while chunk := upload.file.read(self.chunk_size):
                    if not head:
                        head = chunk[:16]
                        self._validate_signature(extension, head)
                    total += len(chunk)
                    if total > self.settings.max_upload_size_bytes:
                        raise AppError(
                            code="file_too_large",
                            message=f"文件超过 {self.settings.max_upload_size_mb} MB 限制",
                            status_code=413,
                        )
                    digest.update(chunk)
                    output.write(chunk)
            if total == 0:
                raise AppError(code="empty_file", message="不允许上传空文件", status_code=400)
        except Exception:
            destination.unlink(missing_ok=True)
            raise

        return SavedUpload(
            storage_key=relative.as_posix(),
            path=destination,
            safe_name=safe_name,
            extension=extension,
            media_type=upload.content_type,
            byte_size=total,
            sha256=digest.hexdigest(),
        )

    @staticmethod
    def remove(saved: SavedUpload) -> None:
        saved.path.unlink(missing_ok=True)
