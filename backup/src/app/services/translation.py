from collections.abc import Callable
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.tables import table
from app.models import Document, DocumentVersion, ProcessingJob
from app.schemas.workflow import TaskAccepted, TranslationCreate


class TranslationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()

    def enqueue(
        self,
        project_id: UUID,
        version_id: UUID,
        payload: TranslationCreate,
        actor_id: UUID | None,
    ) -> TaskAccepted:
        version = self.db.execute(
            select(DocumentVersion.id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(DocumentVersion.id == version_id, Document.project_id == project_id)
        ).scalar_one_or_none()
        if not version:
            raise AppError(
                code="document_version_not_found", message="文献版本不存在", status_code=404
            )
        job = ProcessingJob(
            project_id=project_id,
            document_version_id=version_id,
            job_type="translate_document",
            status="queued",
            progress_percent=0,
            current_stage="waiting",
            idempotency_key=f"translate_document:{version_id}:{payload.target_language}",
            requested_config={
                "document_version_id": str(version_id),
                "target_language": payload.target_language,
                "overwrite": payload.overwrite,
            },
            result_summary={},
            requested_by=actor_id,
        )
        self.db.add(job)
        self.db.commit()
        return TaskAccepted(resource_id=version_id, job_id=job.id)

    def execute(
        self,
        version_id: UUID,
        target_language: str,
        overwrite: bool,
        progress: Callable[[float, str], None],
    ) -> dict[str, Any]:
        api_key = self.settings.deepseek_api_key.get_secret_value()
        if not api_key:
            raise AppError(
                code="translation_api_not_configured",
                message="未配置 DEEPSEEK_API_KEY，无法执行在线翻译",
                status_code=409,
            )
        blocks = table(self.db, "document_blocks")
        translations = table(self.db, "document_translations")
        external_calls = table(self.db, "external_calls")
        document = self.db.execute(
            select(Document, DocumentVersion)
            .join(DocumentVersion, DocumentVersion.document_id == Document.id)
            .where(DocumentVersion.id == version_id)
        ).one_or_none()
        if not document:
            raise AppError(
                code="document_version_not_found", message="文献版本不存在", status_code=404
            )
        document_model, version_model = document
        rows = self.db.execute(
            select(blocks.c.id, blocks.c.content_text)
            .where(blocks.c.document_version_id == version_id, blocks.c.content_text.is_not(None))
            .order_by(blocks.c.page_id, blocks.c.sequence_no)
        ).all()
        if overwrite:
            self.db.execute(
                delete(translations).where(
                    translations.c.document_version_id == version_id,
                    translations.c.target_language == target_language,
                )
            )
        existing = set(
            self.db.scalars(
                select(translations.c.source_block_id).where(
                    translations.c.document_version_id == version_id,
                    translations.c.target_language == target_language,
                )
            ).all()
        )
        translated = 0
        endpoint = self.settings.deepseek_base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        with httpx.Client(timeout=90) as client:
            for index, (block_id, content) in enumerate(rows):
                if block_id in existing or not content.strip():
                    continue
                payload = {
                    "model": self.settings.deepseek_model,
                    "messages": [
                        {
                            "role": "system",
                            "content": f"Translate academic text to {target_language}. Preserve values, units and terminology. Output translation only.",
                        },
                        {"role": "user", "content": content[:12000]},
                    ],
                    "temperature": 0,
                }
                status = "completed"
                error_message = None
                translated_text = None
                usage = {}
                try:
                    response = client.post(endpoint, headers=headers, json=payload)
                    response.raise_for_status()
                    body = response.json()
                    translated_text = body["choices"][0]["message"]["content"].strip()
                    usage = body.get("usage", {})
                except Exception as exc:
                    status = "failed"
                    error_message = str(exc)[:1000]
                self.db.execute(
                    insert(external_calls).values(
                        project_id=document_model.project_id,
                        job_id=None,
                        provider="deepseek",
                        model_name=self.settings.deepseek_model,
                        operation="translate_block",
                        prompt_version="translation-v1",
                        input_units=usage.get("prompt_tokens"),
                        output_units=usage.get("completion_tokens"),
                        status=status,
                        error_message=error_message,
                        metadata={"block_id": str(block_id)},
                    )
                )
                if translated_text:
                    self.db.execute(
                        insert(translations).values(
                            document_version_id=version_id,
                            source_block_id=block_id,
                            source_language=version_model.detected_language
                            or document_model.language,
                            target_language=target_language,
                            translated_text=translated_text,
                            provider="deepseek",
                            model_name=self.settings.deepseek_model,
                            prompt_version="translation-v1",
                            metadata={},
                        )
                    )
                    translated += 1
                if index % 10 == 0:
                    self.db.commit()
                    progress(5 + 90 * (index + 1) / max(len(rows), 1), "translating_blocks")
        self.db.commit()
        return {
            "document_version_id": str(version_id),
            "translated_blocks": translated,
            "target_language": target_language,
        }
