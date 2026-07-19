import hashlib
import io
from collections.abc import Callable
from typing import Any
from uuid import UUID

import pandas as pd
from docx import Document as WordDocument
from docx.shared import Inches, Pt
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.tables import table
from app.models import ProcessingJob, Project, StoredFile
from app.schemas.report import ReportCreate
from app.schemas.workflow import TaskAccepted
from app.services.storage import LocalStorage


class ReportService:
    def __init__(self, db: Session, storage: LocalStorage) -> None:
        self.db = db
        self.storage = storage

    def create(
        self, project_id: UUID, payload: ReportCreate, actor_id: UUID | None
    ) -> TaskAccepted:
        reports = table(self.db, "reports")
        version_no = (
            self.db.scalar(
                select(func.max(reports.c.version_no)).where(
                    reports.c.project_id == project_id, reports.c.title == payload.title
                )
            )
            or 0
        ) + 1
        report_id = self.db.execute(
            insert(reports)
            .values(
                project_id=project_id,
                dataset_version_id=payload.dataset_version_id,
                ml_run_id=payload.ml_run_id,
                optimization_run_id=payload.optimization_run_id,
                version_no=version_no,
                title=payload.title,
                status="queued",
                configuration=payload.configuration,
                generated_by=actor_id,
            )
            .returning(reports.c.id)
        ).scalar_one()
        job = ProcessingJob(
            project_id=project_id,
            job_type="generate_report",
            status="queued",
            progress_percent=0,
            current_stage="waiting",
            idempotency_key=f"generate_report:{report_id}",
            requested_config={"report_id": str(report_id)},
            result_summary={},
            requested_by=actor_id,
        )
        self.db.add(job)
        self.db.commit()
        return TaskAccepted(resource_id=report_id, job_id=job.id)

    def list(self, project_id: UUID) -> list[dict]:
        reports = table(self.db, "reports")
        return [
            dict(row)
            for row in self.db.execute(
                select(reports)
                .where(reports.c.project_id == project_id)
                .order_by(reports.c.created_at.desc())
            ).mappings()
        ]

    @staticmethod
    def _pyplot() -> Any:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        return plt

    @classmethod
    def _add_chart(cls, document: Any, figure: Any, title: str) -> None:
        plt = cls._pyplot()

        buffer = io.BytesIO()
        figure.tight_layout()
        figure.savefig(buffer, format="png", dpi=160, bbox_inches="tight")
        plt.close(figure)
        buffer.seek(0)
        document.add_heading(title, level=2)
        document.add_picture(buffer, width=Inches(6.2))

    def generate(self, report_id: UUID, progress: Callable[[float, str], None]) -> dict[str, Any]:
        reports = table(self.db, "reports")
        datasets = table(self.db, "datasets")
        versions = table(self.db, "dataset_versions")
        ml_runs = table(self.db, "ml_runs")
        ml_models = table(self.db, "ml_models")
        ml_metrics = table(self.db, "ml_metrics")
        ml_predictions = table(self.db, "ml_predictions")
        ml_explanations = table(self.db, "ml_explanations")
        optimizations = table(self.db, "optimization_runs")
        candidates = table(self.db, "optimization_candidates")
        dataset_fields = table(self.db, "dataset_fields")
        dataset_rows = table(self.db, "dataset_rows")
        dataset_cells = table(self.db, "dataset_cells")
        cell_evidence = table(self.db, "dataset_cell_evidence")
        conversion_records = table(self.db, "conversion_records")
        documents = table(self.db, "documents")
        pages = table(self.db, "document_pages")
        report_assets = table(self.db, "report_assets")
        report = (
            self.db.execute(select(reports).where(reports.c.id == report_id))
            .mappings()
            .one_or_none()
        )
        if not report:
            raise AppError(code="report_not_found", message="报告任务不存在", status_code=404)
        self.db.execute(delete(report_assets).where(report_assets.c.report_id == report_id))
        project = self.db.get(Project, report["project_id"])
        if not project:
            raise AppError(code="project_not_found", message="项目不存在", status_code=404)
        version = (
            self.db.execute(select(versions).where(versions.c.id == report["dataset_version_id"]))
            .mappings()
            .one()
        )
        dataset = (
            self.db.execute(select(datasets).where(datasets.c.id == version["dataset_id"]))
            .mappings()
            .one()
        )
        document = WordDocument()
        styles = document.styles
        styles["Normal"].font.name = "Microsoft YaHei"
        styles["Normal"].font.size = Pt(10.5)
        document.add_heading(report["title"], level=0)
        document.add_paragraph(f"项目：{project.name}")
        document.add_paragraph(f"数据集：{dataset['name']}，版本 V{version['version_no']}")
        document.add_paragraph(
            f"数据规模：{version['row_count']} 行，{version['field_count']} 个字段"
        )
        document.add_paragraph(f"数据校验哈希：{version['content_sha256'] or '草稿版本，尚未冻结'}")
        progress(25, "writing_dataset_section")

        document.add_heading("数据处理与可追溯性", level=1)
        document.add_paragraph(
            "系统保留原始值、标准值和建模值三层数据。正式数值均可回溯到原始文献、页码和证据文本。"
        )
        document.add_paragraph("缺失值不进行臆造；图像估计值和人工修改值在数据集中单独标记。")

        source_documents = self.db.execute(
            select(documents.c.title, documents.c.publication_year, documents.c.publication_name)
            .where(documents.c.project_id == project.id, documents.c.deleted_at.is_(None))
            .order_by(documents.c.created_at)
        ).all()
        document.add_heading("文献来源与解析范围", level=1)
        document.add_paragraph(f"本项目共纳入 {len(source_documents)} 篇文献。")
        for title, year, publication in source_documents[:200]:
            document.add_paragraph(
                f"{title or '未命名文献'}；{year or '年份未知'}；{publication or '来源未知'}",
                style="List Bullet",
            )

        field_rows = (
            self.db.execute(
                select(dataset_fields)
                .where(dataset_fields.c.dataset_version_id == version["id"])
                .order_by(dataset_fields.c.position)
            )
            .mappings()
            .all()
        )
        document.add_heading("字段、抽取与单位规则", level=1)
        for field in field_rows:
            document.add_paragraph(
                f"{field['display_name']} ({field['field_key']})；类型={field['data_type']}；"
                f"角色={field['semantic_role']}；校验={field['validation_rules']}",
                style="List Bullet",
            )
        row_ids = list(
            self.db.scalars(
                select(dataset_rows.c.id).where(
                    dataset_rows.c.dataset_version_id == version["id"],
                    dataset_rows.c.is_deleted.is_(False),
                )
            ).all()
        )
        numeric_fields = {
            row["id"]: row["display_name"]
            for row in field_rows
            if row["data_type"] in {"number", "integer", "float", "decimal", "range"}
        }
        matrix_values: dict[UUID, dict[str, float]] = {}
        if row_ids and numeric_fields:
            for row_id, field_id, value in self.db.execute(
                select(
                    dataset_cells.c.row_id, dataset_cells.c.field_id, dataset_cells.c.value_number
                ).where(
                    dataset_cells.c.row_id.in_(row_ids),
                    dataset_cells.c.field_id.in_(list(numeric_fields)),
                    dataset_cells.c.value_number.is_not(None),
                    dataset_cells.c.is_missing.is_(False),
                )
            ):
                matrix_values.setdefault(row_id, {})[numeric_fields[field_id]] = float(value)
        numeric_frame = pd.DataFrame(matrix_values.values())
        if not numeric_frame.empty:
            plt = self._pyplot()

            columns = list(numeric_frame.columns[:6])
            figure, axes = plt.subplots(len(columns), 1, figsize=(7, max(2.4, 2.1 * len(columns))))
            axes_list = [axes] if len(columns) == 1 else list(axes)
            for axis, column in zip(axes_list, columns, strict=False):
                axis.hist(
                    numeric_frame[column].dropna(), bins=min(20, max(5, len(numeric_frame) // 2))
                )
                axis.set_title(column)
                axis.set_ylabel("Count")
            self._add_chart(document, figure, "数据分布")
            self.db.execute(
                insert(report_assets).values(
                    report_id=report_id,
                    asset_type="chart",
                    section_key="data_distribution",
                    title="数据分布",
                    data_payload={"fields": columns},
                    position=10,
                )
            )
            if len(numeric_frame.columns) >= 2:
                correlation = numeric_frame.corr(numeric_only=True)
                figure, axis = plt.subplots(figsize=(7, 5.5))
                image = axis.imshow(correlation, vmin=-1, vmax=1, cmap="coolwarm")
                axis.set_xticks(
                    range(len(correlation.columns)), correlation.columns, rotation=45, ha="right"
                )
                axis.set_yticks(range(len(correlation.index)), correlation.index)
                figure.colorbar(image, ax=axis, label="Correlation")
                self._add_chart(document, figure, "相关性矩阵")
                self.db.execute(
                    insert(report_assets).values(
                        report_id=report_id,
                        asset_type="chart",
                        section_key="correlation",
                        title="相关性矩阵",
                        data_payload={"matrix": correlation.fillna(0).to_dict()},
                        position=20,
                    )
                )

        if report["ml_run_id"]:
            run = (
                self.db.execute(select(ml_runs).where(ml_runs.c.id == report["ml_run_id"]))
                .mappings()
                .one_or_none()
            )
            if run:
                document.add_heading("机器学习模型", level=1)
                document.add_paragraph(
                    f"任务类型：{run['task_type']}；切分策略：{run['split_strategy']}；随机种子：{run['random_seed']}"
                )
                model_rows = (
                    self.db.execute(
                        select(ml_models)
                        .where(ml_models.c.ml_run_id == run["id"])
                        .order_by(ml_models.c.model_no)
                    )
                    .mappings()
                    .all()
                )
                table_doc = document.add_table(rows=1, cols=4)
                for index, title in enumerate(["模型", "状态", "是否选中", "测试指标"]):
                    table_doc.rows[0].cells[index].text = title
                for model in model_rows:
                    metric_rows = (
                        self.db.execute(
                            select(ml_metrics).where(
                                ml_metrics.c.ml_model_id == model["id"],
                                ml_metrics.c.split_name == "test",
                            )
                        )
                        .mappings()
                        .all()
                    )
                    row = table_doc.add_row().cells
                    row[0].text = model["display_name"]
                    row[1].text = model["status"]
                    row[2].text = "是" if model["is_selected"] else "否"
                    row[3].text = ", ".join(
                        f"{item['metric_name']}={item['metric_value']:.4f}"
                        for item in metric_rows
                        if item["metric_value"] is not None
                    )
                    explanation_rows = (
                        self.db.execute(
                            select(ml_explanations).where(
                                ml_explanations.c.ml_model_id == model["id"]
                            )
                        )
                        .mappings()
                        .all()
                    )
                    for explanation in explanation_rows:
                        if explanation["method"] not in {"shap", "permutation_importance"}:
                            continue
                        document.add_heading(
                            f"{model['display_name']} - {explanation['method']}", level=2
                        )
                        features = (explanation["explanation_data"] or {}).get("features", [])
                        for feature in sorted(
                            features,
                            key=lambda item: abs(
                                item.get("mean_absolute_shap", item.get("importance_mean", 0))
                            ),
                            reverse=True,
                        )[:20]:
                            score = feature.get(
                                "mean_absolute_shap", feature.get("importance_mean", 0)
                            )
                            document.add_paragraph(f"{feature.get('name')}: {score:.6g}")
                selected_model = next(
                    (model for model in model_rows if model["is_selected"]),
                    model_rows[0] if model_rows else None,
                )
                if selected_model:
                    prediction_rows = self.db.execute(
                        select(
                            ml_predictions.c.actual_value,
                            ml_predictions.c.predicted_value,
                            ml_predictions.c.residual_value,
                        ).where(
                            ml_predictions.c.ml_model_id == selected_model["id"],
                            ml_predictions.c.split_name == "test",
                        )
                    ).all()
                    actual = [
                        float(row.actual_value["value"])
                        for row in prediction_rows
                        if row.actual_value and row.actual_value.get("value") is not None
                    ]
                    predicted = [
                        float(row.predicted_value["value"])
                        for row in prediction_rows
                        if row.predicted_value and row.predicted_value.get("value") is not None
                    ]
                    residuals = [
                        float(row.residual_value)
                        for row in prediction_rows
                        if row.residual_value is not None
                    ]
                    if actual and len(actual) == len(predicted):
                        plt = self._pyplot()

                        figure, axes = plt.subplots(1, 2, figsize=(9, 4))
                        axes[0].scatter(actual, predicted, alpha=0.8)
                        lower = min([*actual, *predicted])
                        upper = max([*actual, *predicted])
                        axes[0].plot([lower, upper], [lower, upper], linestyle="--", color="black")
                        axes[0].set_xlabel("Actual")
                        axes[0].set_ylabel("Predicted")
                        axes[0].set_title("Actual vs Predicted")
                        if residuals:
                            axes[1].scatter(predicted[: len(residuals)], residuals, alpha=0.8)
                            axes[1].axhline(0, linestyle="--", color="black")
                            axes[1].set_xlabel("Predicted")
                            axes[1].set_ylabel("Residual")
                            axes[1].set_title("Residuals")
                        self._add_chart(document, figure, "实测、预测与残差")
                        self.db.execute(
                            insert(report_assets).values(
                                report_id=report_id,
                                asset_type="chart",
                                section_key="prediction_residual",
                                title="实测、预测与残差",
                                data_payload={"model_id": str(selected_model["id"])},
                                position=30,
                            )
                        )
                    selected_explanation = (
                        self.db.execute(
                            select(ml_explanations).where(
                                ml_explanations.c.ml_model_id == selected_model["id"],
                                ml_explanations.c.method.in_(["shap", "permutation_importance"]),
                            )
                        )
                        .mappings()
                        .first()
                    )
                    if selected_explanation:
                        features = (selected_explanation["explanation_data"] or {}).get(
                            "features", []
                        )
                        ranked = sorted(
                            features,
                            key=lambda item: abs(
                                item.get("mean_absolute_shap", item.get("importance_mean", 0))
                            ),
                            reverse=True,
                        )[:20]
                        if ranked:
                            plt = self._pyplot()

                            names = [str(item.get("name")) for item in reversed(ranked)]
                            scores = [
                                float(
                                    item.get("mean_absolute_shap", item.get("importance_mean", 0))
                                )
                                for item in reversed(ranked)
                            ]
                            figure, axis = plt.subplots(figsize=(7, max(3, len(names) * 0.3)))
                            axis.barh(names, scores)
                            axis.set_xlabel(selected_explanation["method"])
                            self._add_chart(document, figure, "特征重要性")
                            self.db.execute(
                                insert(report_assets).values(
                                    report_id=report_id,
                                    asset_type="chart",
                                    section_key="feature_importance",
                                    title="特征重要性",
                                    data_payload={
                                        "model_id": str(selected_model["id"]),
                                        "features": ranked,
                                    },
                                    position=40,
                                )
                            )
        progress(55, "writing_model_section")

        if report["optimization_run_id"]:
            optimization = (
                self.db.execute(
                    select(optimizations).where(optimizations.c.id == report["optimization_run_id"])
                )
                .mappings()
                .one_or_none()
            )
            if optimization:
                document.add_heading("目标参数优化候选", level=1)
                document.add_paragraph(
                    f"方法：{optimization['method']}；目标：{optimization['objective_config']}"
                )
                rows = (
                    self.db.execute(
                        select(candidates)
                        .where(candidates.c.optimization_run_id == optimization["id"])
                        .order_by(candidates.c.rank_no)
                        .limit(20)
                    )
                    .mappings()
                    .all()
                )
                for item in rows:
                    document.add_paragraph(
                        f"#{item['rank_no']} 输入={item['input_values']}，预测={item['predicted_values']}，目标分数={item['objective_score']}"
                    )
        document.add_heading("单位转换记录", level=1)
        conversion_rows = self.db.execute(
            select(
                conversion_records.c.source_value,
                conversion_records.c.target_value,
                conversion_records.c.source_unit_text,
                conversion_records.c.formula_used,
                conversion_records.c.status,
            )
            .join(dataset_cells, dataset_cells.c.id == conversion_records.c.dataset_cell_id)
            .join(dataset_rows, dataset_rows.c.id == dataset_cells.c.row_id)
            .where(dataset_rows.c.dataset_version_id == version["id"])
            .limit(500)
        ).all()
        if conversion_rows:
            conversion_table = document.add_table(rows=1, cols=5)
            for index, title in enumerate(["原值", "目标值", "原单位", "公式", "状态"]):
                conversion_table.rows[0].cells[index].text = title
            for conversion_item in conversion_rows:
                cells_doc = conversion_table.add_row().cells
                cells_doc[0].text = str(conversion_item.source_value)
                cells_doc[1].text = str(conversion_item.target_value)
                cells_doc[2].text = str(conversion_item.source_unit_text or "")
                cells_doc[3].text = conversion_item.formula_used
                cells_doc[4].text = conversion_item.status
        else:
            document.add_paragraph("本版本无单位转换记录。")

        document.add_heading("证据索引", level=1)
        evidence_rows = self.db.execute(
            select(
                documents.c.title,
                pages.c.page_no,
                cell_evidence.c.evidence_text,
                cell_evidence.c.bbox,
            )
            .join(dataset_cells, dataset_cells.c.id == cell_evidence.c.dataset_cell_id)
            .join(dataset_rows, dataset_rows.c.id == dataset_cells.c.row_id)
            .join(versions, versions.c.id == dataset_rows.c.dataset_version_id)
            .join(documents, documents.c.id == dataset_rows.c.source_document_id)
            .join(pages, pages.c.id == cell_evidence.c.page_id)
            .where(dataset_rows.c.dataset_version_id == version["id"])
            .order_by(documents.c.title, pages.c.page_no)
            .limit(1000)
        ).all()
        if evidence_rows:
            evidence_table = document.add_table(rows=1, cols=4)
            for index, title in enumerate(["文献", "页码", "原文证据", "坐标"]):
                evidence_table.rows[0].cells[index].text = title
            for evidence_item in evidence_rows:
                cells_doc = evidence_table.add_row().cells
                cells_doc[0].text = evidence_item.title or ""
                cells_doc[1].text = str(evidence_item.page_no)
                cells_doc[2].text = evidence_item.evidence_text
                cells_doc[3].text = str(evidence_item.bbox or "")
        else:
            document.add_paragraph("本版本未关联证据索引。")
        document.add_heading("局限性", level=1)
        document.add_paragraph(
            "模型输出是基于已审核文献数据的统计预测，不替代真实实验和专业判断。超出训练数据范围的候选条件应重新验证。"
        )
        progress(80, "saving_report")

        buffer = io.BytesIO()
        document.save(buffer)
        content = buffer.getvalue()
        saved = self.storage.save_bytes(
            project.id,
            category="reports",
            extension="docx",
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        stored = StoredFile(
            organization_id=project.organization_id,
            project_id=project.id,
            storage_provider="local",
            storage_key=saved.storage_key,
            original_name=f"{report['title']}-v{report['version_no']}.docx",
            safe_name=saved.safe_name,
            extension="docx",
            media_type=saved.media_type,
            byte_size=saved.byte_size,
            sha256=saved.sha256,
            purpose="report",
            security_status="generated",
            metadata_json={},
        )
        self.db.add(stored)
        self.db.flush()
        self.db.execute(
            update(reports)
            .where(reports.c.id == report_id)
            .values(
                status="completed",
                output_file_id=stored.id,
                content_sha256=hashlib.sha256(content).hexdigest(),
                completed_at=func.now(),
            )
        )
        self.db.commit()
        return {"report_id": str(report_id), "file_id": str(stored.id), "sha256": saved.sha256}

    def output_path(self, project_id: UUID, report_id: UUID):
        reports = table(self.db, "reports")
        row = (
            self.db.execute(
                select(reports).where(reports.c.id == report_id, reports.c.project_id == project_id)
            )
            .mappings()
            .one_or_none()
        )
        if not row or not row["output_file_id"]:
            raise AppError(code="report_not_ready", message="报告尚未生成", status_code=409)
        stored = self.db.get(StoredFile, row["output_file_id"])
        if not stored:
            raise AppError(code="report_file_not_found", message="报告文件不存在", status_code=404)
        return self.storage.path_for_key(stored.storage_key), stored.original_name
