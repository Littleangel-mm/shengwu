import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.core.errors import AppError


@dataclass(frozen=True)
class OCRImage:
    page_no: int
    path: Path
    pixel_width: int
    pixel_height: int
    page_width: float
    page_height: float


@dataclass(frozen=True)
class OCRLine:
    text: str
    confidence: float
    bbox: list[float]


@dataclass(frozen=True)
class OCRPage:
    page_no: int
    lines: list[OCRLine]

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def confidence(self) -> float | None:
        if not self.lines:
            return None
        return sum(line.confidence for line in self.lines) / len(self.lines)


class PaddleOCRService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = Path.cwd()

    def status(self) -> dict[str, Any]:
        python_path = self.settings.ocr_python.resolve()
        detection = self.settings.ocr_detection_model_dir.resolve()
        recognition = self.settings.ocr_recognition_model_dir.resolve()
        checks = {
            "python": python_path.is_file(),
            "detection_model": detection.is_dir(),
            "recognition_model": recognition.is_dir(),
        }
        return {
            "status": "ready"
            if self.settings.ocr_enabled and all(checks.values())
            else "unavailable",
            "enabled": self.settings.ocr_enabled,
            "engine": "PaddleOCR",
            "checks": checks,
        }

    def recognize(self, images: list[OCRImage]) -> dict[int, OCRPage]:
        if not images:
            return {}
        status = self.status()
        if status["status"] != "ready":
            raise AppError(
                code="ocr_unavailable",
                message="PaddleOCR 运行环境或模型未就绪",
                status_code=503,
                details=status["checks"],
            )
        runner = Path(__file__).resolve().parents[1] / "ocr_runner.py"
        with tempfile.TemporaryDirectory(prefix="research-ocr-") as temporary:
            temporary_path = Path(temporary)
            manifest_path = temporary_path / "manifest.json"
            output_path = temporary_path / "result.json"
            manifest = {
                "detection_model_name": self.settings.ocr_detection_model_name,
                "recognition_model_name": self.settings.ocr_recognition_model_name,
                "detection_model_dir": str(self.settings.ocr_detection_model_dir.resolve()),
                "recognition_model_dir": str(self.settings.ocr_recognition_model_dir.resolve()),
                "min_confidence": self.settings.ocr_min_confidence,
                "images": [
                    {
                        "page_no": image.page_no,
                        "path": str(image.path.resolve()),
                        "pixel_width": image.pixel_width,
                        "pixel_height": image.pixel_height,
                        "page_width": image.page_width,
                        "page_height": image.page_height,
                    }
                    for image in images
                ],
            }
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            environment = os.environ.copy()
            environment.update(
                {
                    "FLAGS_use_mkldnn": "0",
                    "FLAGS_enable_pir_api": "0",
                    "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
                }
            )
            try:
                completed = subprocess.run(
                    [
                        str(self.settings.ocr_python.resolve()),
                        str(runner),
                        "--manifest",
                        str(manifest_path),
                        "--output",
                        str(output_path),
                    ],
                    cwd=self.root,
                    env=environment,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.settings.ocr_timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise AppError(
                    code="ocr_timeout", message="PaddleOCR 识别超时", status_code=504
                ) from exc
            if completed.returncode != 0 or not output_path.exists():
                error = (completed.stderr or completed.stdout or "OCR failed")[-2000:]
                raise AppError(
                    code="ocr_failed", message="PaddleOCR 识别失败", status_code=502, details=error
                )
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        pages: dict[int, OCRPage] = {}
        for page in payload.get("pages", []):
            scale_x = float(page["page_width"]) / max(int(page["pixel_width"]), 1)
            scale_y = float(page["page_height"]) / max(int(page["pixel_height"]), 1)
            lines = [
                OCRLine(
                    text=line["text"],
                    confidence=float(line["confidence"]),
                    bbox=[
                        round(float(line["bbox"][0]) * scale_x, 3),
                        round(float(line["bbox"][1]) * scale_y, 3),
                        round(float(line["bbox"][2]) * scale_x, 3),
                        round(float(line["bbox"][3]) * scale_y, 3),
                    ],
                )
                for line in page.get("lines", [])
            ]
            page_no = int(page["page_no"])
            pages[page_no] = OCRPage(page_no=page_no, lines=lines)
        return pages
