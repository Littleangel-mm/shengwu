import json
from pathlib import Path
from types import SimpleNamespace

from app.core.config import Settings
from app.services.ocr import OCRImage, OCRLine, OCRPage, PaddleOCRService


def test_ocr_status_checks_relative_runtime_and_models(tmp_path: Path, monkeypatch) -> None:
    python_path = tmp_path / "ocr-python.exe"
    detection = tmp_path / "det"
    recognition = tmp_path / "rec"
    python_path.touch()
    detection.mkdir()
    recognition.mkdir()
    monkeypatch.chdir(tmp_path)
    service = PaddleOCRService(
        Settings(
            ocr_python=Path("ocr-python.exe"),
            ocr_detection_model_dir=Path("det"),
            ocr_recognition_model_dir=Path("rec"),
        )
    )
    assert service.status()["status"] == "ready"


def test_ocr_page_text_and_confidence() -> None:
    page = OCRPage(
        page_no=1,
        lines=[
            OCRLine(text="first", confidence=0.8, bbox=[0, 0, 10, 10]),
            OCRLine(text="second", confidence=1.0, bbox=[0, 10, 10, 20]),
        ],
    )
    assert page.text == "first\nsecond"
    assert page.confidence == 0.9


def test_ocr_result_coordinates_are_scaled(tmp_path: Path, monkeypatch) -> None:
    python_path = tmp_path / "ocr-python.exe"
    detection = tmp_path / "det"
    recognition = tmp_path / "rec"
    image_path = tmp_path / "page.png"
    python_path.touch()
    detection.mkdir()
    recognition.mkdir()
    image_path.touch()
    monkeypatch.chdir(tmp_path)

    def fake_run(command, **kwargs):
        output_path = Path(command[command.index("--output") + 1])
        manifest_path = Path(command[command.index("--manifest") + 1])
        image = json.loads(manifest_path.read_text(encoding="utf-8"))["images"][0]
        output_path.write_text(
            json.dumps(
                {
                    "pages": [
                        {
                            **image,
                            "lines": [
                                {
                                    "text": "temperature",
                                    "confidence": 0.95,
                                    "bbox": [20, 40, 220, 80],
                                }
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("app.services.ocr.subprocess.run", fake_run)
    service = PaddleOCRService(
        Settings(
            ocr_python=Path("ocr-python.exe"),
            ocr_detection_model_dir=Path("det"),
            ocr_recognition_model_dir=Path("rec"),
        )
    )
    result = service.recognize([OCRImage(1, image_path, 1000, 2000, 500.0, 1000.0)])[1]
    assert result.lines[0].bbox == [10.0, 20.0, 110.0, 40.0]
    assert result.lines[0].confidence == 0.95
