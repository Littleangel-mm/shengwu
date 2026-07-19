import argparse
import json
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("FLAGS_enable_pir_api", "0")
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")


def _result_payload(result: Any) -> dict[str, Any]:
    payload = result.json
    if callable(payload):
        payload = payload()
    return payload.get("res", payload)


def run(manifest_path: Path, output_path: Path) -> None:
    from paddleocr import PaddleOCR

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ocr = PaddleOCR(
        text_detection_model_name=manifest["detection_model_name"],
        text_recognition_model_name=manifest["recognition_model_name"],
        text_detection_model_dir=manifest["detection_model_dir"],
        text_recognition_model_dir=manifest["recognition_model_dir"],
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        enable_mkldnn=False,
        device="cpu",
    )
    pages = []
    for image in manifest["images"]:
        predicted = list(
            ocr.predict(
                image["path"],
                text_rec_score_thresh=float(manifest.get("min_confidence", 0.5)),
            )
        )
        result = _result_payload(predicted[0]) if predicted else {}
        texts = result.get("rec_texts", [])
        scores = result.get("rec_scores", [])
        boxes = result.get("rec_boxes", [])
        lines = [
            {"text": str(text), "confidence": float(score), "bbox": list(box)}
            for text, score, box in zip(texts, scores, boxes, strict=False)
            if str(text).strip()
        ]
        pages.append({**image, "lines": lines})
    output_path.write_text(
        json.dumps({"engine": "PaddleOCR", "pages": pages}, ensure_ascii=False),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.manifest, args.output)


if __name__ == "__main__":
    main()
