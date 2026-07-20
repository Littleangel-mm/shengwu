from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    Uuid,
    create_engine,
)
from sqlalchemy.orm import Session

from app.api import deps
from app.core.errors import AppError
from app.models import AppUser, Organization, Project
from app.services import audit as audit_module
from app.services import project as project_module
from app.services import term as term_module
from app.services.project import ProjectService
from app.services.term import TermService


def _project_tables(engine) -> dict[str, Any]:
    metadata = MetaData()
    audit_logs = Table(
        "audit_logs",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("organization_id", Uuid, nullable=False),
        Column("project_id", Uuid),
        Column("actor_id", Uuid),
        Column("entity_type", String(100), nullable=False),
        Column("entity_id", Uuid),
        Column("action", String(100), nullable=False),
        Column("before_value", JSON),
        Column("after_value", JSON),
        Column("reason", String),
    )
    metadata.create_all(engine)
    return {"audit_logs": audit_logs, "projects": Project.__table__}


@pytest.fixture
def project_db(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    cast(Table, AppUser.__table__).create(engine)
    cast(Table, Organization.__table__).create(engine)
    cast(Table, Project.__table__).create(engine)
    tables = _project_tables(engine)
    monkeypatch.setattr(project_module, "table", lambda _db, name: tables[name])
    monkeypatch.setattr(audit_module, "table", lambda _db, name: tables[name])
    with Session(engine) as session:
        yield session, tables


def _user(session: Session, email: str) -> AppUser:
    user = AppUser(
        id=uuid4(),
        email=email,
        display_name=email.split("@")[0],
        password_hash=None,
        preferences={},
    )
    session.add(user)
    return user


def _organization(session: Session, owner: AppUser, slug: str) -> Organization:
    organization = Organization(
        id=uuid4(), name=slug, slug=slug, settings={}, created_by=owner.id
    )
    session.add(organization)
    return organization


def _project(session: Session, organization: Organization, owner: AppUser, slug: str) -> Project:
    project = Project(
        id=uuid4(),
        organization_id=organization.id,
        name=slug,
        slug=slug,
        description=None,
        research_domain=None,
        settings={},
        created_by=owner.id,
    )
    session.add(project)
    return project


def test_archive_sets_status_and_writes_audit(project_db) -> None:
    session, tables = project_db
    owner = _user(session, "owner@example.com")
    organization = _organization(session, owner, "arch-org")
    project = _project(session, organization, owner, "arch-project")
    session.commit()

    response = ProjectService(session).archive(project.id, owner.id)

    assert response.status == "archived"
    assert response.archived_at is not None
    session.refresh(project)
    assert project.status == "archived"
    assert project.archived_at is not None
    action = session.scalar(
        tables["audit_logs"].select().with_only_columns(tables["audit_logs"].c.action)
    )
    assert action == "project.archived"


def test_unarchive_clears_status_and_writes_audit(project_db) -> None:
    session, tables = project_db
    owner = _user(session, "owner@example.com")
    organization = _organization(session, owner, "unarch-org")
    project = _project(session, organization, owner, "unarch-project")
    session.commit()

    ProjectService(session).archive(project.id, owner.id)
    response = ProjectService(session).unarchive(project.id, owner.id)

    assert response.status == "active"
    assert response.archived_at is None
    session.refresh(project)
    assert project.status == "active"
    assert project.archived_at is None
    actions = list(
        session.scalars(
            tables["audit_logs"].select().with_only_columns(tables["audit_logs"].c.action)
        )
    )
    assert actions == ["project.archived", "project.unarchived"]


def test_update_still_works_on_archived_project(project_db) -> None:
    session, _tables = project_db
    from app.schemas.project import ProjectUpdate

    owner = _user(session, "owner@example.com")
    organization = _organization(session, owner, "upd-org")
    project = _project(session, organization, owner, "upd-project")
    session.commit()

    ProjectService(session).archive(project.id, owner.id)
    updated = ProjectService(session).update(project.id, ProjectUpdate(name="renamed"))
    assert updated.name == "renamed"
    assert updated.status == "archived"

    ProjectService(session).soft_delete(project.id)
    session.refresh(project)
    assert project.status == "deleted"


@pytest.mark.parametrize(
    ("roles", "allowed"),
    [
        (("viewer", None), False),
        (("editor", None), False),
        (("owner", None), True),
        ((None, "admin"), True),
        ((None, "owner"), True),
    ],
)
def test_archive_requires_owner_or_organization_admin(monkeypatch, roles, allowed) -> None:
    actor_id = uuid4()
    db = cast(Session, object())
    monkeypatch.setattr(deps, "_project_role", lambda *_: roles)
    if allowed:
        assert deps.require_project_admin(uuid4(), db, actor_id) == actor_id
    else:
        with pytest.raises(AppError, match="项目所有者"):
            deps.require_project_admin(uuid4(), db, actor_id)


def _term_tables(engine) -> dict[str, Any]:
    metadata = MetaData()
    term_categories = Table(
        "term_categories",
        metadata,
        Column("id", Uuid, primary_key=True, default=uuid4),
        Column("project_id", Uuid, nullable=False),
        Column("code", String(100), nullable=False),
        Column("name", String(200), nullable=False),
        Column("description", Text),
        Column("position", Integer, nullable=False, default=0),
        Column("settings", JSON, nullable=False, default=dict),
        Column("created_at", DateTime(timezone=True), default=lambda: datetime.now(UTC)),
        Column("updated_at", DateTime(timezone=True), default=lambda: datetime.now(UTC)),
    )
    terms = Table(
        "terms",
        metadata,
        Column("id", Uuid, primary_key=True, default=uuid4),
        Column("project_id", Uuid, nullable=False),
        Column("category_id", Uuid),
        Column("canonical_name", Text, nullable=False),
        Column("normalized_name", Text),
        Column("status", String(32), nullable=False, default="candidate"),
        Column("is_selected", Boolean, nullable=False, default=False),
        Column("deleted_at", DateTime(timezone=True)),
    )
    term_aliases = Table(
        "term_aliases",
        metadata,
        Column("id", Uuid, primary_key=True, default=uuid4),
        Column("term_id", Uuid, nullable=False),
        Column("alias_text", Text, nullable=False),
        Column("normalized_alias", Text),
        Column("created_at", DateTime(timezone=True), default=lambda: datetime.now(UTC)),
    )
    term_occurrences = Table(
        "term_occurrences",
        metadata,
        Column("id", Uuid, primary_key=True, default=uuid4),
        Column("project_id", Uuid, nullable=False),
        Column("term_id", Uuid),
        Column("occurrence_count", Integer, nullable=False, default=1),
    )
    metadata.create_all(engine)
    return {
        "term_categories": term_categories,
        "terms": terms,
        "term_aliases": term_aliases,
        "term_occurrences": term_occurrences,
    }


@pytest.fixture
def term_db(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    tables = _term_tables(engine)
    monkeypatch.setattr(term_module, "table", lambda _db, name: tables[name])
    with Session(engine) as session:
        yield session, tables


def _insert_term(
    session: Session,
    tables: dict[str, Any],
    project_id: UUID,
    canonical_name: str,
    *,
    category_id: UUID | None = None,
    aliases: list[str] | None = None,
    occurrences: int = 0,
    deleted: bool = False,
) -> UUID:
    term_id = uuid4()
    session.execute(
        tables["terms"].insert().values(
            id=term_id,
            project_id=project_id,
            category_id=category_id,
            canonical_name=canonical_name,
            normalized_name=canonical_name.casefold().strip(),
            status="confirmed",
            is_selected=True,
            deleted_at=datetime.now(UTC) if deleted else None,
        )
    )
    for alias in aliases or []:
        session.execute(
            tables["term_aliases"].insert().values(
                id=uuid4(),
                term_id=term_id,
                alias_text=alias,
                normalized_alias=alias.casefold().strip(),
            )
        )
    if occurrences:
        session.execute(
            tables["term_occurrences"].insert().values(
                id=uuid4(),
                project_id=project_id,
                term_id=term_id,
                occurrence_count=occurrences,
            )
        )
    return term_id


def test_apply_default_template_creates_three_categories(term_db) -> None:
    session, _tables = term_db
    project_id = uuid4()

    categories = TermService(session).apply_default_category_template(project_id)

    codes = {item["code"] for item in categories}
    assert codes == {"process_parameters", "chemical_indicators", "sensory_evaluation"}
    assert all(item["description"] for item in categories)


def test_apply_default_template_is_idempotent(term_db) -> None:
    session, tables = term_db
    project_id = uuid4()
    service = TermService(session)

    first = service.apply_default_category_template(project_id)
    second = service.apply_default_category_template(project_id)

    assert len(first) == len(second) == 3
    total = session.scalar(
        tables["term_categories"]
        .select()
        .with_only_columns(tables["term_categories"].c.id)
        .where(tables["term_categories"].c.project_id == project_id)
    )
    assert total is not None
    count = len(
        list(
            session.scalars(
                tables["term_categories"]
                .select()
                .with_only_columns(tables["term_categories"].c.id)
                .where(tables["term_categories"].c.project_id == project_id)
            )
        )
    )
    assert count == 3


def test_apply_default_template_preserves_existing_and_fills_missing(term_db) -> None:
    session, tables = term_db
    project_id = uuid4()
    session.execute(
        tables["term_categories"].insert().values(
            id=uuid4(),
            project_id=project_id,
            code="process_parameters",
            name="自定义工艺参数",
            description="用户自定义",
            position=0,
            settings={},
        )
    )
    session.commit()

    categories = TermService(session).apply_default_category_template(project_id)

    by_code = {item["code"]: item for item in categories}
    assert by_code["process_parameters"]["name"] == "自定义工艺参数"
    assert "chemical_indicators" in by_code
    assert "sensory_evaluation" in by_code


def test_synonym_suggestions_cluster_similar_terms(term_db) -> None:
    session, tables = term_db
    project_id = uuid4()
    category_id = uuid4()
    session.execute(
        tables["term_categories"].insert().values(
            id=category_id,
            project_id=project_id,
            code="process_parameters",
            name="工艺参数",
            description="",
            position=0,
            settings={},
        )
    )
    _insert_term(
        session, tables, project_id, "发酵温度", category_id=category_id, occurrences=10
    )
    _insert_term(session, tables, project_id, "发酵温度值", category_id=category_id, occurrences=3)
    _insert_term(session, tables, project_id, "pH", category_id=category_id, occurrences=5)
    session.commit()

    clusters = TermService(session).suggest_synonyms(project_id)

    assert len(clusters) == 1
    cluster = clusters[0]
    names = {item["display_name"] for item in cluster["terms"]}
    assert names == {"发酵温度", "发酵温度值"}
    assert cluster["suggested_standard"]["display_name"] == "发酵温度"
    assert cluster["similarity"] >= 85.0


def test_synonym_suggestions_use_alias_overlap(term_db) -> None:
    session, tables = term_db
    project_id = uuid4()
    _insert_term(session, tables, project_id, "总酸含量", aliases=["TA"], occurrences=4)
    _insert_term(session, tables, project_id, "可滴定酸度", aliases=["ta"], occurrences=2)
    session.commit()

    clusters = TermService(session).suggest_synonyms(project_id)

    assert len(clusters) == 1
    assert clusters[0]["similarity"] == 100.0
    names = {item["display_name"] for item in clusters[0]["terms"]}
    assert names == {"总酸含量", "可滴定酸度"}


def test_synonym_suggestions_ignore_dissimilar_and_deleted(term_db) -> None:
    session, tables = term_db
    project_id = uuid4()
    _insert_term(session, tables, project_id, "发酵温度")
    _insert_term(session, tables, project_id, "蛋白质含量")
    _insert_term(session, tables, project_id, "感官评分")
    _insert_term(session, tables, project_id, "发酵温度", deleted=True)
    session.commit()

    clusters = TermService(session).suggest_synonyms(project_id)

    assert clusters == []


def test_synonym_suggestions_do_not_mutate_terms(term_db) -> None:
    session, tables = term_db
    project_id = uuid4()
    _insert_term(session, tables, project_id, "发酵时间", occurrences=6)
    _insert_term(session, tables, project_id, "发酵时间长", occurrences=1)
    session.commit()

    TermService(session).suggest_synonyms(project_id)

    statuses = set(
        session.scalars(
            tables["terms"].select().with_only_columns(tables["terms"].c.status)
        )
    )
    assert statuses == {"confirmed"}
    alive = len(
        list(
            session.scalars(
                tables["terms"]
                .select()
                .with_only_columns(tables["terms"].c.id)
                .where(tables["terms"].c.deleted_at.is_(None))
            )
        )
    )
    assert alive == 2
