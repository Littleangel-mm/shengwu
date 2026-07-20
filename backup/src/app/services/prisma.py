import io
from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.tables import table
from app.models import Project

# PRISMA 2020 流程的标准计数字段（缺省 0），外加“排除原因”明细列表。
PRISMA_FIELDS: tuple[str, ...] = (
    "identified_databases",
    "identified_registers",
    "duplicates_removed",
    "records_screened",
    "records_excluded",
    "reports_sought",
    "reports_not_retrieved",
    "reports_assessed",
    "studies_included",
)

PRISMA_LABELS: dict[str, str] = {
    "identified_databases": "数据库检索记录数",
    "identified_registers": "注册库检索记录数",
    "duplicates_removed": "去重/筛选前剔除数",
    "records_screened": "筛选记录数",
    "records_excluded": "筛选排除数",
    "reports_sought": "全文获取数",
    "reports_not_retrieved": "未获取全文数",
    "reports_assessed": "全文评估数",
    "studies_included": "最终纳入研究数",
}


class PrismaService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _ensure_project(self, project_id: UUID) -> Project:
        project = self.db.get(Project, project_id)
        if not project or project.deleted_at is not None:
            raise AppError(code="project_not_found", message="项目不存在", status_code=404)
        return project

    @staticmethod
    def _normalize(data: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for field in PRISMA_FIELDS:
            try:
                normalized[field] = max(0, int(data.get(field, 0) or 0))
            except (TypeError, ValueError):
                normalized[field] = 0
        reasons = []
        for item in data.get("reports_excluded", []) or []:
            reason = str(item.get("reason", "")).strip()
            if not reason:
                continue
            try:
                count = max(0, int(item.get("count", 0) or 0))
            except (TypeError, ValueError):
                count = 0
            reasons.append({"reason": reason[:200], "count": count})
        normalized["reports_excluded"] = reasons
        return normalized

    def get_flow(self, project_id: UUID) -> dict[str, Any]:
        self._ensure_project(project_id)
        flows = table(self.db, "prisma_flows")
        row = (
            self.db.execute(select(flows).where(flows.c.project_id == project_id))
            .mappings()
            .one_or_none()
        )
        if not row:
            return {
                "project_id": str(project_id),
                "data": self._normalize({}),
                "notes": None,
                "exists": False,
            }
        result = dict(row)
        result["data"] = self._normalize(result.get("data") or {})
        result["exists"] = True
        return result

    def upsert_flow(
        self, project_id: UUID, data: dict[str, Any], notes: str | None, actor_id: UUID | None
    ) -> dict[str, Any]:
        self._ensure_project(project_id)
        flows = table(self.db, "prisma_flows")
        normalized = self._normalize(data)
        existing = self.db.scalar(select(flows.c.id).where(flows.c.project_id == project_id))
        if existing:
            self.db.execute(
                update(flows)
                .where(flows.c.project_id == project_id)
                .values(data=normalized, notes=notes, updated_by=actor_id, updated_at=func.now())
            )
        else:
            self.db.execute(
                insert(flows).values(
                    project_id=project_id, data=normalized, notes=notes, updated_by=actor_id
                )
            )
        self.db.commit()
        return self.get_flow(project_id)

    @staticmethod
    def render_diagram(data: dict[str, Any]) -> bytes:
        """用 matplotlib 绘制 PRISMA 2020 流程计数图，返回 PNG 字节。"""
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False

        excluded_reasons = data.get("reports_excluded") or []
        reason_text = "；".join(
            f"{item['reason']}({item['count']})" for item in excluded_reasons[:5]
        )
        boxes = [
            (
                "识别",
                f"数据库检索 {data.get('identified_databases', 0)} 条\n"
                f"注册库检索 {data.get('identified_registers', 0)} 条",
            ),
            ("去重", f"筛选前剔除 {data.get('duplicates_removed', 0)} 条"),
            (
                "筛选",
                f"筛选 {data.get('records_screened', 0)} 条\n"
                f"排除 {data.get('records_excluded', 0)} 条",
            ),
            (
                "全文评估",
                f"获取全文 {data.get('reports_sought', 0)} 条\n"
                f"未获取 {data.get('reports_not_retrieved', 0)} 条\n"
                f"评估 {data.get('reports_assessed', 0)} 条"
                + (f"\n排除原因: {reason_text}" if reason_text else ""),
            ),
            ("纳入", f"最终纳入研究 {data.get('studies_included', 0)} 项"),
        ]
        figure, axis = plt.subplots(figsize=(6.2, 8.6))
        axis.set_xlim(0, 10)
        axis.set_ylim(0, len(boxes) * 2)
        axis.axis("off")
        centers = []
        for index, (title, body) in enumerate(reversed(boxes)):
            y = index * 2 + 1
            centers.append(y)
            axis.add_patch(
                FancyBboxPatch(
                    (1.5, y - 0.7),
                    7,
                    1.4,
                    boxstyle="round,pad=0.1",
                    linewidth=1.2,
                    edgecolor="#8a6d3b",
                    facecolor="#f5efe1",
                )
            )
            axis.text(
                5,
                y,
                f"{title}\n{body}",
                ha="center",
                va="center",
                fontsize=9,
                wrap=True,
            )
        for index in range(len(centers) - 1):
            axis.add_patch(
                FancyArrowPatch(
                    (5, centers[index] + 0.7),
                    (5, centers[index + 1] - 0.7),
                    arrowstyle="-|>",
                    mutation_scale=14,
                    linewidth=1.1,
                    color="#8a6d3b",
                )
            )
        buffer = io.BytesIO()
        figure.tight_layout()
        figure.savefig(buffer, format="png", dpi=150, bbox_inches="tight")
        plt.close(figure)
        return buffer.getvalue()
