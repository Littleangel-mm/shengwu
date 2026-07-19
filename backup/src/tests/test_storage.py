from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.core.config import Settings
from app.services.storage import LocalStorage


def test_pdf_is_saved_under_relative_storage_root(tmp_path: Path) -> None:
    settings = Settings(storage_root=tmp_path, max_upload_size_mb=1)
    storage = LocalStorage(settings)
    upload = UploadFile(filename="paper.pdf", file=BytesIO(b"%PDF-1.7\ncontent"))

    saved = storage.save(uuid4(), upload)

    assert saved.path.exists()
    assert saved.storage_key.startswith("uploads/")
    assert saved.sha256
    storage.remove(saved)
