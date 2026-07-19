import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.services.document import DocumentService
from app.services.extraction import ExtractionService
from app.services.ml import MLService
from app.services.ocr import OCRLine
from app.services.parser import DocumentParser
from app.services.search import SearchService
from app.services.storage import LocalStorage, SavedUpload


def test_semantic_scores_rank_related_text_first() -> None:
    texts = [
        "Fermentation temperature strongly changed the product yield.",
        "The unrelated control discusses publication formatting.",
    ]
    scores = SearchService._semantic_scores(texts, ["fermentation yield"])
    assert scores[0][0] > scores[1][0]


def test_dimension_keys_link_treatment_and_timepoint() -> None:
    group, timepoint = ExtractionService._dimension_keys("处理组: A 发酵时间 48 h", "document-1")
    assert "treatment=A" in group
    assert timepoint == "48h"


def test_figure_metadata_excludes_axis_ticks_from_direct_values() -> None:
    metadata = DocumentParser._figure_metadata(
        [
            OCRLine("Yield", 0.99, [200, 10, 300, 30]),
            OCRLine("10", 0.99, [5, 100, 30, 120]),
            OCRLine("42.5", 0.98, [250, 80, 310, 105]),
        ],
        width=400,
        height=200,
    )
    assert [item["text"] for item in metadata["direct_values"]] == ["42.5"]


def test_augmentation_only_adds_training_rows() -> None:
    frame = pd.DataFrame({"temperature": [20.0, 25.0, 30.0, 35.0]})
    target = pd.Series([1.0, 2.0, 3.0, 4.0])
    augmented_x, augmented_y, groups, count = MLService._augment_training(
        frame,
        target,
        ["a", "b", "c", "d"],
        {"temperature": "number"},
        {"enabled": True, "factor": 0.5, "noise_std": 0.01},
        42,
    )
    assert count == 2
    assert len(augmented_x) == len(augmented_y) == len(groups) == 6
    assert np.isfinite(augmented_x["temperature"]).all()


def test_zip_path_traversal_is_rejected(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../paper.txt", "content")
    saved = SavedUpload(
        storage_key="unsafe.zip",
        path=archive_path,
        safe_name="unsafe.zip",
        extension="zip",
        media_type="application/zip",
        byte_size=archive_path.stat().st_size,
        sha256="0" * 64,
    )
    service = DocumentService(None, LocalStorage(Settings(storage_root=tmp_path)))  # type: ignore[arg-type]
    with pytest.raises(AppError, match="ZIP"):
        service._archive_uploads(saved)


def test_safe_zip_returns_supported_child_upload(tmp_path: Path) -> None:
    archive_path = tmp_path / "safe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("folder/paper.txt", "content")
    saved = SavedUpload(
        storage_key="safe.zip",
        path=archive_path,
        safe_name="safe.zip",
        extension="zip",
        media_type="application/zip",
        byte_size=archive_path.stat().st_size,
        sha256="0" * 64,
    )
    service = DocumentService(None, LocalStorage(Settings(storage_root=tmp_path)))  # type: ignore[arg-type]
    uploads = service._archive_uploads(saved)
    assert [upload.filename for upload in uploads] == ["paper.txt"]
    assert uploads[0].file.read() == b"content"
