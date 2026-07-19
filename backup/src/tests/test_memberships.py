from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Uuid,
    create_engine,
)
from sqlalchemy.orm import Session

from app.api import deps
from app.core.errors import AppError
from app.models import AppUser, Organization, Project
from app.schemas.organization import OrganizationMemberInvite, OrganizationMemberUpdate
from app.schemas.project import ProjectMemberInvite, ProjectMemberUpdate
from app.services import audit as audit_module
from app.services import organization as organization_module
from app.services import project as project_module
from app.services.organization import OrganizationService
from app.services.project import ProjectService


def _membership_tables(engine) -> dict[str, Any]:
    metadata = MetaData()
    organization_members = Table(
        "organization_members",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("organization_id", Uuid, nullable=False),
        Column("user_id", Uuid, nullable=False),
        Column("role", String(32), nullable=False),
        Column("status", String(32), nullable=False, default="active"),
        Column(
            "joined_at",
            DateTime(timezone=True),
            nullable=False,
            default=lambda: datetime.now(UTC),
        ),
        Column(
            "created_at",
            DateTime(timezone=True),
            nullable=False,
            default=lambda: datetime.now(UTC),
        ),
        Column(
            "updated_at",
            DateTime(timezone=True),
            nullable=False,
            default=lambda: datetime.now(UTC),
        ),
    )
    project_members = Table(
        "project_members",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("project_id", Uuid, nullable=False),
        Column("user_id", Uuid, nullable=False),
        Column("role", String(32), nullable=False),
        Column("permissions", JSON, nullable=False, default=dict),
        Column(
            "created_at",
            DateTime(timezone=True),
            nullable=False,
            default=lambda: datetime.now(UTC),
        ),
        Column(
            "updated_at",
            DateTime(timezone=True),
            nullable=False,
            default=lambda: datetime.now(UTC),
        ),
    )
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
    return {
        "organization_members": organization_members,
        "project_members": project_members,
        "audit_logs": audit_logs,
        "projects": Project.__table__,
    }


@pytest.fixture
def membership_db(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    cast(Table, AppUser.__table__).create(engine)
    cast(Table, Organization.__table__).create(engine)
    cast(Table, Project.__table__).create(engine)
    tables = _membership_tables(engine)
    monkeypatch.setattr(organization_module, "table", lambda _db, name: tables[name])
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
        id=uuid4(),
        name=slug,
        slug=slug,
        settings={},
        created_by=owner.id,
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


def _insert_member(table: Table, session: Session, **values) -> UUID:
    member_id = uuid4()
    now = datetime.now(UTC)
    defaults = {"id": member_id, "created_at": now, "updated_at": now}
    if table.name == "organization_members":
        defaults.update(status="active", joined_at=now)
    else:
        defaults.update(permissions={})
    session.execute(table.insert().values(**defaults, **values))
    return member_id


@pytest.mark.parametrize(
    ("roles", "allowed"),
    [
        (("viewer", None), False),
        (("editor", None), False),
        (("owner", None), True),
        ((None, "admin"), True),
    ],
)
def test_project_member_management_requires_owner_or_organization_admin(
    monkeypatch, roles, allowed
) -> None:
    actor_id = uuid4()
    db = cast(Session, object())
    monkeypatch.setattr(deps, "_project_role", lambda *_: roles)
    if allowed:
        assert deps.require_project_admin(uuid4(), db, actor_id) == actor_id
    else:
        with pytest.raises(AppError, match="项目所有者"):
            deps.require_project_admin(uuid4(), db, actor_id)


def test_project_permissions_keep_unknown_project_non_enumerable(monkeypatch) -> None:
    monkeypatch.setattr(deps, "_project_role", lambda *_: None)
    with pytest.raises(AppError) as error:
        deps.require_project_admin(uuid4(), cast(Session, object()), uuid4())
    assert error.value.status_code == 404
    assert error.value.code == "project_not_found"


def test_last_owners_cannot_be_demoted_or_removed(membership_db) -> None:
    session, tables = membership_db
    owner = _user(session, "owner@example.com")
    organization = _organization(session, owner, "owners")
    project = _project(session, organization, owner, "owners-project")
    session.flush()
    _insert_member(
        tables["organization_members"],
        session,
        organization_id=organization.id,
        user_id=owner.id,
        role="owner",
    )
    _insert_member(
        tables["project_members"],
        session,
        project_id=project.id,
        user_id=owner.id,
        role="owner",
    )
    session.commit()

    with pytest.raises(AppError) as organization_error:
        OrganizationService(session).update_member(
            organization.id,
            owner.id,
            OrganizationMemberUpdate(role="admin"),
            owner.id,
        )
    assert organization_error.value.code == "last_organization_owner"

    with pytest.raises(AppError) as project_error:
        ProjectService(session).remove_member(project.id, owner.id, owner.id)
    assert project_error.value.code == "last_project_owner"


def test_invite_by_email_adds_members_and_audit_records(membership_db) -> None:
    session, tables = membership_db
    owner = _user(session, "owner@example.com")
    invited = _user(session, "invitee@example.com")
    organization = _organization(session, owner, "invite-org")
    project = _project(session, organization, owner, "invite-project")
    session.commit()

    organization_member = OrganizationService(session).invite_member(
        organization.id,
        OrganizationMemberInvite(email="INVITEE@example.com", role="member"),
        owner.id,
    )
    project_member = ProjectService(session).invite_member(
        project.id,
        ProjectMemberInvite(email="invitee@example.com", role="viewer"),
        owner.id,
    )

    assert organization_member.user_id == invited.id
    assert project_member.user_id == invited.id
    assert project_member.status == "active"
    actions = set(session.scalars(tables["audit_logs"].select().with_only_columns(
        tables["audit_logs"].c.action
    )))
    assert actions == {"organization_member.invited", "project_member.invited"}


def test_viewer_editor_owner_roles_and_cross_project_isolation(membership_db) -> None:
    session, tables = membership_db
    owner = _user(session, "owner@example.com")
    editor = _user(session, "editor@example.com")
    viewer = _user(session, "viewer@example.com")
    organization = _organization(session, owner, "role-org")
    other_organization = _organization(session, owner, "other-org")
    project = _project(session, organization, owner, "role-project")
    other_project = _project(session, other_organization, owner, "other-project")
    session.flush()
    for user, role in ((owner, "owner"), (editor, "editor"), (viewer, "viewer")):
        _insert_member(
            tables["project_members"],
            session,
            project_id=project.id,
            user_id=user.id,
            role=role,
        )
    session.commit()

    service = ProjectService(session)
    assert service.current_membership(project.id, owner.id).can_manage_members
    editor_membership = service.current_membership(project.id, editor.id)
    assert editor_membership.role == "editor"
    assert editor_membership.can_write
    viewer_membership = service.current_membership(project.id, viewer.id)
    assert viewer_membership.role == "viewer"
    assert not viewer_membership.can_write

    with pytest.raises(AppError) as error:
        service.current_membership(other_project.id, viewer.id)
    assert error.value.code == "project_not_found"


def test_member_change_is_scoped_to_project_and_audited(membership_db) -> None:
    session, tables = membership_db
    owner = _user(session, "owner@example.com")
    member = _user(session, "member@example.com")
    organization = _organization(session, owner, "audit-org")
    project = _project(session, organization, owner, "audit-project")
    other_project = _project(session, organization, owner, "audit-other")
    session.flush()
    _insert_member(
        tables["project_members"],
        session,
        project_id=project.id,
        user_id=member.id,
        role="viewer",
    )
    session.commit()

    with pytest.raises(AppError) as error:
        ProjectService(session).update_member(
            other_project.id,
            member.id,
            ProjectMemberUpdate(role="editor"),
            owner.id,
        )
    assert error.value.code == "project_member_not_found"

    updated = ProjectService(session).update_member(
        project.id,
        member.id,
        ProjectMemberUpdate(role="editor"),
        owner.id,
    )
    assert updated.role == "editor"
    action = session.scalar(
        tables["audit_logs"]
        .select()
        .with_only_columns(tables["audit_logs"].c.action)
    )
    assert action == "project_member.role_updated"
