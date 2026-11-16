"""Keep dashboard recommendations and counters intact without full inventory reads."""

from datetime import datetime, timedelta, timezone
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from internshipos import models as m, service
from internshipos.db import Base


@pytest.fixture(params=["sqlite", "postgresql"])
def dashboard_db(request):
    if request.param == "postgresql":
        url = os.getenv("TEST_POSTGRES_URL")
        if not url:
            pytest.skip("Requires isolated CI PostgreSQL service")
    else:
        url = "sqlite:///:memory:"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    try:
        with engine.connect() as connection, connection.begin() as transaction:
            with Session(bind=connection, expire_on_commit=False) as db:
                yield db
            transaction.rollback()
    finally:
        engine.dispose()


def test_dashboard_distinguishes_visible_saved_roles_from_verified_recommendations(dashboard_db, monkeypatch):
    db = dashboard_db
    now = datetime(2026, 11, 17, 10, tzinfo=timezone.utc)
    monkeypatch.setattr(service, "utcnow", lambda: now)
    monkeypatch.setattr("internshipos.shortlist.utcnow", lambda: now)
    company = m.Company(name="Priority Studio", metadata_json={"company_priority": {"score": 100}})
    other = m.Company(name="Regional Lab")
    db.add_all([company, other])
    db.flush()
    official = m.CompanySource(company_id=company.id, provider="workday", url="https://company.example/job", verified=True, status="complete")
    unverified = m.CompanySource(company_id=company.id, provider="capture", url="https://other.example/job")
    db.add_all([official, unverified])
    db.flush()

    def opportunity(label, **overrides):
        values = dict(company_id=company.id, title=label, role_family="SWE", opportunity_type="internship", country="IN",
                      location="Bengaluru", description="Employer-stated technical requirements", fit_score=40,
                      canonical_url=f"https://company.example/jobs/{label}", first_seen=now - timedelta(hours=1),
                      data={"description_checked_at": now.isoformat()})
        item = m.Opportunity(**(values | overrides))
        db.add(item)
        db.flush()
        return item

    def observe(item, board, **overrides):
        values = dict(opportunity_id=item.id, company_source_id=board.id, external_id=item.title,
                      last_seen=now, last_detail_checked=now)
        db.add(m.JobSource(**(values | overrides)))

    canonical = opportunity("canonical", saved=True, deadline=now + timedelta(days=2))
    mirror = opportunity("mirror", saved=True, data={"duplicate_of": canonical.id})
    canonical.data = {"mirror_ids": [mirror.id], "description_source_id": official.id, "deadline_precision": "date"}
    observe(mirror, official)
    second = opportunity("fallback", company_id=other.id, fit_score=90, deadline=now + timedelta(days=1))
    observe(second, official)
    stale = opportunity("stale", saved=True)
    observe(stale, official, last_seen=now - timedelta(days=3))
    observe(stale, unverified)
    foreign = opportunity("foreign", country="US", location="New York", saved=True)
    observe(foreign, official)
    untargeted = opportunity("outside-role-preferences", role_family="Data")
    observe(untargeted, official)
    phd = opportunity("doctoral", title="PhD intern")
    observe(phd, official)
    full_time = opportunity("full-time", opportunity_type="other", saved=True)
    observe(full_time, official)
    db.add_all([
        m.Setting(key="roles", value=["SWE"]),
        m.Setting(key="personal_location_policy", value=True),
        m.Application(opportunity_id=canonical.id, stage="interview"),
        m.Application(opportunity_id=foreign.id, stage="rejected"),
        m.Task(opportunity_id=second.id, title="Review the role", due_at=now + timedelta(hours=12)),
    ])
    db.flush()

    dashboard = service.dashboard(db)
    assert [role["id"] for role in dashboard["top_opportunities"]] == [canonical.id, second.id]
    assert dashboard["top_opportunities"][0]["shortlist"]["detail_checked_at"] == now.isoformat().replace("+00:00", "Z")
    assert dashboard["stats"] == {"new_opportunities": 2, "saved": 4, "applications": 2, "active_applications": 1,
                                  "interviews": 1, "companies": 2, "sources_healthy": 1}
    assert dashboard["daily_discoveries"][-1] == {"date": now.date().isoformat(), "count": 2}
    assert [(row["opportunity_id"], row["title"]) for row in dashboard["deadlines"]] == [
        (second.id, "Review the role"), (canonical.id, "canonical")]
    assert dashboard["deadlines"][1]["date_precision"] == "date"
    assert [row["id"] for row in dashboard["source_health"]] == [unverified.id, official.id]

    db.add(m.Setting(key="shortlist_exclusions", value={"opportunity_ids": [mirror.id]}))
    db.flush()
    excluded = service.dashboard(db)
    assert [role["id"] for role in excluded["top_opportunities"]] == [second.id]
    assert excluded["stats"]["saved"] == 3 and excluded["stats"]["applications"] == 2
