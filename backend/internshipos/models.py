"""Single-user relational model; JSON contains observations, never implicit truth."""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, utcnow


def uid() -> str:
    return str(uuid4())


class Identified:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)


class Created:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Updated(Created):
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Company(Identified, Updated, Base):
    __tablename__ = "companies"
    name: Mapped[str] = mapped_column(String(300), index=True)
    domain: Mapped[str | None] = mapped_column(String(300), index=True)
    careers_url: Mapped[str | None] = mapped_column(Text)
    logo_url: Mapped[str | None] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str] = mapped_column(Text, default="")
    industry: Mapped[str | None] = mapped_column(String(200))
    locations: Mapped[list] = mapped_column(JSON, default=list)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    sources: Mapped[list[CompanySource]] = relationship(back_populates="company")


class CompanySource(Identified, Updated, Base):
    __tablename__ = "company_sources"
    __table_args__ = (UniqueConstraint("company_id", "provider", "url", name="uq_company_provider_url"),)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    company: Mapped[Company] = relationship(back_populates="sources")
    provider: Mapped[str] = mapped_column(String(80), index=True)
    url: Mapped[str] = mapped_column(Text)
    tenant: Mapped[str | None] = mapped_column(String(300))
    board: Mapped[str | None] = mapped_column(String(300))
    priority: Mapped[int] = mapped_column(Integer, default=2)
    cadence_hours: Mapped[float] = mapped_column(Float, default=12)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="unverified")
    last_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    job_count: Mapped[int] = mapped_column(Integer, default=0)


class FetchRun(Identified, Created, Base):
    __tablename__ = "fetch_runs"
    company_source_id: Mapped[str] = mapped_column(ForeignKey("company_sources.id"), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40), default="running")
    complete: Mapped[bool] = mapped_column(Boolean, default=False)
    coverage_scope: Mapped[str] = mapped_column(String(300), default="full")
    observed_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Opportunity(Identified, Updated, Base):
    __tablename__ = "opportunities"
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    company: Mapped[Company] = relationship()
    title: Mapped[str] = mapped_column(String(800))
    description: Mapped[str] = mapped_column(Text, default="")
    description_html: Mapped[str] = mapped_column(Text, default="")
    role_family: Mapped[str] = mapped_column(String(80), default="unclear", index=True)
    opportunity_type: Mapped[str] = mapped_column(String(80), default="unclear", index=True)
    location: Mapped[str] = mapped_column(String(800), default="")
    country: Mapped[str | None] = mapped_column(String(120))
    work_mode: Mapped[str] = mapped_column(String(60), default="unknown")
    compensation: Mapped[dict] = mapped_column(JSON, default=dict)
    skills: Mapped[list] = mapped_column(JSON, default=list)
    requirements: Mapped[list] = mapped_column(JSON, default=list)
    responsibilities: Mapped[list] = mapped_column(JSON, default=list)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    last_verified: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)
    saved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    canonical_url: Mapped[str | None] = mapped_column(Text)
    apply_url: Mapped[str | None] = mapped_column(Text)
    requisition_id: Mapped[str | None] = mapped_column(String(300), index=True)
    fit_score: Mapped[float | None] = mapped_column(Float)
    fit_confidence: Mapped[str] = mapped_column(String(40), default="unassessed")
    worth_score: Mapped[float | None] = mapped_column(Float)
    eligibility: Mapped[str] = mapped_column(String(60), default="unclear")
    trust_state: Mapped[str] = mapped_column(String(60), default="unassessed")
    risk_reasons: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    sources: Mapped[list[JobSource]] = relationship(back_populates="opportunity")
    __table_args__ = (
        CheckConstraint("fit_score IS NULL OR (fit_score >= 0 AND fit_score <= 100)", name="ck_fit_range"),
        CheckConstraint("worth_score IS NULL OR (worth_score >= 0 AND worth_score <= 100)", name="ck_worth_range"),
    )


class JobSource(Identified, Created, Base):
    __tablename__ = "job_sources"
    __table_args__ = (UniqueConstraint("company_source_id", "external_id", name="uq_scoped_external_job"),)
    company_source_id: Mapped[str] = mapped_column(ForeignKey("company_sources.id"), index=True)
    company_source: Mapped[CompanySource] = relationship()
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), index=True)
    opportunity: Mapped[Opportunity] = relationship(back_populates="sources")
    external_id: Mapped[str] = mapped_column(String(700))
    requisition_id: Mapped[str | None] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(Text)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_detail_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_hash: Mapped[str | None] = mapped_column(String(64))
    missed_complete_runs: Mapped[int] = mapped_column(Integer, default=0)
    first_missing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40), default="active")


class Snapshot(Identified, Created, Base):
    __tablename__ = "snapshots"
    job_source_id: Mapped[str] = mapped_column(ForeignKey("job_sources.id"), index=True)
    fetch_run_id: Mapped[str] = mapped_column(ForeignKey("fetch_runs.id"), index=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    normalized: Mapped[dict] = mapped_column(JSON, default=dict)


class IdentityDecision(Identified, Created, Base):
    __tablename__ = "identity_decisions"
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), index=True)
    candidate_id: Mapped[str | None] = mapped_column(ForeignKey("opportunities.id"), index=True)
    job_source_id: Mapped[str | None] = mapped_column(ForeignKey("job_sources.id"))
    decision: Mapped[str] = mapped_column(String(40))
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Evidence(Identified, Created, Base):
    __tablename__ = "evidence"
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), index=True)
    snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("snapshots.id"), index=True)
    field: Mapped[str] = mapped_column(String(200))
    value: Mapped[dict | list | str | int | float | None] = mapped_column(JSON)
    source_url: Mapped[str | None] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(80), default="source")
    confidence: Mapped[str] = mapped_column(String(40), default="observed")
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Evaluation(Identified, Created, Base):
    __tablename__ = "evaluations"
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), index=True)
    profile_version_id: Mapped[str | None] = mapped_column(ForeignKey("profile_versions.id"))
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[str] = mapped_column(String(80), default="deterministic-v1")
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Application(Identified, Updated, Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("opportunity_id", "attempt", name="uq_application_attempt"),)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), index=True)
    opportunity: Mapped[Opportunity] = relationship()
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    stage: Mapped[str] = mapped_column(String(40), default="ready", index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resume_version_id: Mapped[str | None] = mapped_column(ForeignKey("resume_versions.id"))
    notes: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class ApplicationEvent(Identified, Created, Base):
    __tablename__ = "application_events"
    __table_args__ = (UniqueConstraint("application_id", "dedupe_key", name="uq_application_event_key"),)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(100))
    from_stage: Mapped[str | None] = mapped_column(String(40))
    to_stage: Mapped[str | None] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(80), default="user")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    dedupe_key: Mapped[str | None] = mapped_column(String(300))
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Task(Identified, Updated, Base):
    __tablename__ = "tasks"
    title: Mapped[str] = mapped_column(String(1000))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    application_id: Mapped[str | None] = mapped_column(ForeignKey("applications.id"), index=True)
    opportunity_id: Mapped[str | None] = mapped_column(ForeignKey("opportunities.id"), index=True)
    kind: Mapped[str] = mapped_column(String(60), default="manual")
    notes: Mapped[str] = mapped_column(Text, default="")
    date_precision: Mapped[str] = mapped_column(String(40), default="unknown")
    dedupe_key: Mapped[str | None] = mapped_column(String(300), unique=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Activity(Identified, Created, Base):
    __tablename__ = "activity"
    kind: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(1000))
    body: Mapped[str] = mapped_column(Text, default="")
    entity_type: Mapped[str | None] = mapped_column(String(100))
    entity_id: Mapped[str | None] = mapped_column(String(36), index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProfileVersion(Identified, Created, Base):
    __tablename__ = "profile_versions"
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Resume(Identified, Created, Base):
    __tablename__ = "resumes"
    name: Mapped[str] = mapped_column(String(300))
    role_focus: Mapped[str] = mapped_column(String(100), default="general")
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class ResumeVersion(Identified, Created, Base):
    __tablename__ = "resume_versions"
    resume_id: Mapped[str] = mapped_column(ForeignKey("resumes.id"), index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    artifact_path: Mapped[str | None] = mapped_column(Text)
    artifact_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(60), default="draft")


class Project(Identified, Updated, Base):
    __tablename__ = "projects"
    name: Mapped[str] = mapped_column(String(500))
    github_url: Mapped[str | None] = mapped_column(Text, unique=True)
    technologies: Mapped[list] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(Text, default="")
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_bullets: Mapped[list] = mapped_column(JSON, default=list)
    role_tags: Mapped[list] = mapped_column(JSON, default=list)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Integration(Identified, Updated, Base):
    __tablename__ = "integrations"
    provider: Mapped[str] = mapped_column(String(80), unique=True)
    status: Mapped[str] = mapped_column(String(80), default="disconnected")
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    credentials_encrypted: Mapped[str | None] = mapped_column(Text)


class EmailMessage(Identified, Created, Base):
    __tablename__ = "email_messages"
    provider_message_id: Mapped[str] = mapped_column(String(300), unique=True)
    thread_id: Mapped[str | None] = mapped_column(String(300), index=True)
    sender: Mapped[str] = mapped_column(Text, default="")
    subject: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(80), default="review")
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailLink(Identified, Created, Base):
    __tablename__ = "email_links"
    __table_args__ = (UniqueConstraint("email_message_id", "application_id", "event_type", name="uq_email_application_event"),)
    email_message_id: Mapped[str] = mapped_column(ForeignKey("email_messages.id"), index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(100))
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class CalendarLink(Identified, Created, Base):
    __tablename__ = "calendar_links"
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), unique=True)
    external_id: Mapped[str | None] = mapped_column(String(400), unique=True)
    etag: Mapped[str | None] = mapped_column(String(500))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(80), default="pending")


class Notification(Identified, Created, Base):
    __tablename__ = "notifications"
    title: Mapped[str] = mapped_column(String(1000))
    body: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(80), default="info")
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict | list | str | float | int | bool | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AIUsage(Identified, Created, Base):
    __tablename__ = "ai_usage"
    action: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(80))
    model: Mapped[str] = mapped_column(String(200))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0)
    reserved_usd: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(80), default="reserved")
    request_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    __table_args__ = (CheckConstraint("cost_usd >= 0 AND reserved_usd >= 0", name="ck_ai_nonnegative"),)


Index("ix_opportunity_company_requisition", Opportunity.company_id, Opportunity.requisition_id)
