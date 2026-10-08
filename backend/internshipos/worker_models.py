"""Durable worker tables shared by module-entry workers and API imports."""
from uuid import uuid4
from sqlalchemy import String, JSON, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base, utcnow


class BackgroundJob(Base):
    __tablename__ = 'background_jobs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: uuid4().hex)
    kind: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default='pending', index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str] = mapped_column(String(1000), nullable=True)


class WorkerLease(Base):
    """Tokens prevent an expired owner releasing a replacement worker's lease."""
    __tablename__ = 'collection_worker_leases'
    name: Mapped[str] = mapped_column(String(80), primary_key=True)
    token: Mapped[str] = mapped_column(String(36))
    started_at: Mapped[object] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[object] = mapped_column(DateTime(timezone=True), index=True)
