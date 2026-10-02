"""Core behavioral regression tests. All records are isolated test fixtures."""
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from internshipos.db import Base, utcnow
from internshipos import domain, models as m, service, seed


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


def source(db, *, provider="greenhouse", name="Example Labs", domain_name="example.test", verified=True, url=None):
    company = db.scalar(select(m.Company).where(m.Company.name == name))
    if not company:
        company = m.Company(name=name, domain=domain_name, verified=verified)
        db.add(company)
        db.flush()
    board = m.CompanySource(company_id=company.id, provider=provider, url=url or f"https://jobs.example.test/{provider}", verified=verified, enabled=True)
    db.add(board)
    db.commit()
    return board


def job(id="j1", title="Software Engineering Intern", **extra):
    return {"external_id": id, "title": title, "description": "Develop software using Python and SQL. Work with an engineering team and mentor.",
            "location": "Bangalore, India", "canonical_url": f"https://careers.example.test/jobs/{id}",
            "requisition_id": f"req-{id}", **extra}


def ingest(db, board, jobs=None, **kwargs):
    return service.ingest_batch(db, board.id, [job()] if jobs is None else jobs, complete=kwargs.pop("complete", True), **kwargs)


def only_op(db):
    return db.scalar(select(m.Opportunity))


def test_url_identity_preserves_real_parameters():
    assert domain.canonicalize_url("https://CAREERS.example.test/jobs/42/?jobId=42&utm_source=mail#apply") == "https://careers.example.test/jobs/42?jobId=42"
    assert domain.canonicalize_url("https://careers.example.test/jobs?jobId=41") != domain.canonicalize_url("https://careers.example.test/jobs?jobId=42")
    for url in ["javascript:alert(1)", "file:///secrets", "http://localhost/jobs", "https://user:pass@example.test", "http://127.0.0.1/jobs"]:
        assert domain.canonicalize_url(url) is None


def test_classification_avoids_internal_substring_and_excludes_sales():
    assert domain.classify("Maintain internal services", "Software Engineer")["opportunity_type"] == "other"
    assert domain.classify("Sell AI products with Python", "Sales Intern")["role_family"] == "excluded"
    result = domain.classify("Develop ML models using PyTorch", "Machine Learning Intern")
    assert result["opportunity_type"] == "internship"
    assert result["role_family"] == "AI_ML"
    assert "pytorch" in result["skills"]


def test_skill_aliases_do_not_match_java_inside_javascript():
    assert domain.extract_skills("JavaScript and PostgreSQL using sklearn") == ["javascript", "postgresql", "scikit-learn"]


def test_empty_profile_is_uncertainty_not_zero_or_ineligible():
    result = domain.evaluate({"role_family": "SWE", "skills": ["python"], "requirements": [{"type": "graduation_year", "min": 2027, "max": 2028}]}, {})
    assert result["fit_score"] is None
    assert result["worth_score"] is None
    assert result["fit_lower"] == 0 and result["fit_upper"] == 100
    assert result["eligibility"] == "unclear"
    assert result["unknowns"]


def test_cgpa_scale_mismatch_remains_unknown():
    op = {"requirements": [{"type": "cgpa", "min": 8, "scale": 10}]}
    result = domain.evaluate(op, {"cgpa": 3.9, "cgpa_scale": 4})
    assert result["eligibility_checks"][0]["result"] == "unknown"
    assert result["eligibility"] != "probably ineligible"


def test_fit_weights_and_unknown_interval():
    op = {"role_family": "SWE", "skills": ["python", "sql"], "location": "Bengaluru, India", "requirements": [], "data": {}}
    result = domain.evaluate(op, {"skills": ["python"], "preferred_roles": ["SWE"], "preferred_locations": ["Bangalore"]})
    assert sum(d["weight"] for d in result["fit_dimensions"]) == 100
    assert result["fit_lower"] <= result["fit_score"] <= result["fit_upper"]
    assert result["fit_upper"] > result["fit_lower"]
    assert result["evidence_coverage"] == 60


def test_dates_preserve_unknown_and_relative_anchor():
    assert domain.parse_date("rolling applications") is None
    assert domain.parse_date("October 14") is None
    anchor = domain.parse_date("2026-10-02T08:00:00+05:30")
    assert domain.parse_date("2 days ago", observed_at=anchor).date().isoformat() == "2026-09-30"


def test_ingest_is_idempotent_and_snapshots_only_changes(db):
    board = source(db)
    first = ingest(db, board)
    second = ingest(db, board)
    assert first["created"] == 1 and second["created"] == 0 and second["unchanged"] == 1
    assert db.scalar(select(func.count()).select_from(m.Opportunity)) == 1
    assert db.scalar(select(func.count()).select_from(m.Snapshot)) == 1
    assert db.scalar(select(func.count()).select_from(m.FetchRun)) == 2
    assert only_op(db).location == "Bengaluru, India"
    assert only_op(db).fit_score is None
    assert db.scalar(select(func.count()).select_from(m.Evidence)) > 0
    ingest(db, board, [job(description="Changed Python requirements")])
    assert db.scalar(select(func.count()).select_from(m.Snapshot)) == 2


def test_scoped_ids_do_not_merge_employers(db):
    a = source(db)
    b = source(db, name="Different Employer", domain_name="different.test", url="https://different.test/jobs")
    ingest(db, a)
    ingest(db, b)
    assert db.scalar(select(func.count()).select_from(m.Opportunity)) == 2


def test_same_title_different_requisitions_stay_distinct(db):
    board = source(db)
    ingest(db, board, [job("1"), job("2")])
    assert db.scalar(select(func.count()).select_from(m.Opportunity)) == 2
    decision = db.scalar(select(m.IdentityDecision))
    assert decision.decision == "distinct"


def test_exact_canonical_url_associates_sources_without_losing_observations(db):
    a = source(db)
    b = source(db, provider="capture", verified=False)
    ingest(db, a)
    ingest(db, b, [job("mirror", requisition_id="req-j1", canonical_url=job()["canonical_url"])], complete=False, coverage_scope="capture")
    assert db.scalar(select(func.count()).select_from(m.Opportunity)) == 1
    assert db.scalar(select(func.count()).select_from(m.JobSource)) == 2
    assert db.scalar(select(m.IdentityDecision)).decision == "exact_url"
    stats = service.analytics(db)
    assert stats["summary"]["canonical_opportunities"] == 1
    assert stats["summary"]["source_appearances"] == 2


def test_conflicting_requisition_same_url_never_merges(db):
    a = source(db)
    b = source(db, provider="capture", verified=False)
    ingest(db, a)
    ingest(db, b, [job("mirror", requisition_id="different", canonical_url=job()["canonical_url"])])
    assert db.scalar(select(func.count()).select_from(m.Opportunity)) == 2


def test_reused_external_id_changed_requisition_quarantines(db):
    board = source(db)
    ingest(db, board)
    result = ingest(db, board, [job(requisition_id="new-unrelated-requisition")])
    assert result["complete"] is False and result["invalid"] == 1
    assert only_op(db).requisition_id == "req-j1"
    assert db.scalar(select(m.JobSource)).missed_complete_runs == 0


@pytest.mark.parametrize("kwargs", [{"complete": False}, {"coverage_scope": "India-intern-filter"}, {"error": "403 challenge"}, {"observed_count": 50}])
def test_partial_filtered_failed_or_truncated_never_advance_absence(db, kwargs):
    board = source(db)
    ingest(db, board)
    result = ingest(db, board, [], **kwargs)
    assert result["complete"] is False
    appearance = db.scalar(select(m.JobSource))
    assert appearance.missed_complete_runs == 0
    assert only_op(db).status == "active"


def test_sudden_empty_is_quarantined_before_absence_and_grace(db):
    board = source(db)
    ingest(db, board)
    zero1 = ingest(db, board, [])
    assert zero1["status"] == "quarantined"
    assert db.scalar(select(m.JobSource)).missed_complete_runs == 0
    ingest(db, board, [])
    appearance = db.scalar(select(m.JobSource))
    assert appearance.missed_complete_runs == 1
    appearance.first_missing_at = utcnow() - timedelta(hours=49)
    db.commit()
    ingest(db, board, [])
    assert appearance.status == "confirmed_closed"
    assert only_op(db).status == "confirmed_closed"
    ingest(db, board)
    assert only_op(db).status == "active" and appearance.missed_complete_runs == 0


def test_two_healthy_partial_board_absences_become_possible_not_immediate_closed(db):
    board = source(db)
    ingest(db, board, [job("1"), job("2"), job("3")])
    ingest(db, board, [job("2"), job("3")])
    ingest(db, board, [job("2"), job("3")])
    missing = db.scalar(select(m.JobSource).where(m.JobSource.external_id == "1"))
    assert missing.status == "possibly_closed"


def test_sparse_list_does_not_erase_full_jd(db):
    board = source(db)
    ingest(db, board)
    original = only_op(db).description
    ingest(db, board, [job(description="", description_html="")])
    assert only_op(db).description == original


def test_aggregator_discovers_actual_company_and_preserves_global_source(db):
    board = source(db, provider="unstop", name="Unstop discovery", domain_name="unstop.com", verified=False)
    ingest(db, board, [job(company_name="Independent Employer", company_domain="independent.test")], complete=False, coverage_scope="query")
    opportunity = only_op(db)
    assert opportunity.company.name == "Independent Employer"
    assert not opportunity.company.verified
    assert db.scalar(select(m.JobSource)).company_source_id == board.id
    assert opportunity.company_id != board.company_id
    ingest(db, board, [job(company_name="Independent Employer", company_domain="independent.test")], complete=False, coverage_scope="query")
    assert db.scalar(select(func.count()).select_from(m.Company)) == 2


def test_aggregator_missing_employer_is_not_platform_job(db):
    board = source(db, provider="freehire", name="Freehire source", verified=False)
    result = ingest(db, board)
    assert result["invalid"] == 1
    assert db.scalar(select(func.count()).select_from(m.Opportunity)) == 0


def test_lower_authority_mirror_cannot_overwrite_verified_jd(db):
    a = source(db)
    b = source(db, provider="capture", verified=False)
    ingest(db, a)
    original = only_op(db).description
    ingest(db, b, [job(description="Contradictory mirror text")], complete=False)
    assert only_op(db).description == original
    assert db.scalar(select(func.count()).select_from(m.Snapshot)) == 2


def test_application_ready_not_submitted_and_late_email_cannot_regress(db):
    board = source(db)
    ingest(db, board)
    app = service.create_application(db, {"opportunity_id": only_op(db).id})
    assert app["stage"] == "ready" and app["submitted_at"] is None
    app = service.update_application(db, app["id"], {"stage": "applied"})
    assert app["submitted_at"]
    service.update_application(db, app["id"], {"stage": "interview"})
    app = service.update_application(db, app["id"], {"stage": "applied", "source": "gmail", "dedupe_key": "mail:1"})
    assert app["stage"] == "interview"
    n = len(app["events"])
    app = service.update_application(db, app["id"], {"stage": "applied", "source": "gmail", "dedupe_key": "mail:1"})
    assert len(app["events"]) == n


def test_save_undo_and_conflicting_newer_edit(db):
    board = source(db)
    ingest(db, board)
    op = only_op(db)
    service.save_opportunity(db, op.id, {"saved": True})
    event1 = db.scalar(select(m.Activity).where(m.Activity.kind == "opportunity.updated").order_by(m.Activity.created_at.desc()))
    service.undo_activity(db, event1.id)
    assert op.saved is False
    service.save_opportunity(db, op.id, {"notes": "first"})
    event2 = db.scalar(select(m.Activity).where(m.Activity.kind == "opportunity.updated").order_by(m.Activity.created_at.desc()))
    service.save_opportunity(db, op.id, {"notes": "second"})
    with pytest.raises(ValueError, match="newer edit"):
        service.undo_activity(db, event2.id)
    assert op.notes == "second"


def test_profile_version_and_task_date_precision(db):
    first = service.save_profile(db, {"skills": ["Python"]})
    second = service.save_profile(db, {"skills": ["Python", "SQL"]})
    assert first["id"] != second["id"]
    assert db.scalar(select(func.count()).select_from(m.ProfileVersion)) == 2
    task = service.save_task(db, {"title": "Review role", "due_at": "2026-10-12"})
    assert task["date_precision"] == "date"
    assert task["due_at"].startswith("2026-10-12")
    with pytest.raises(ValueError):
        service.save_task(db, {"title": "Bad date", "due_at": "sometime"})
    db.rollback()


def test_settings_do_not_expose_internal_secret_cache_and_validate_auto_scope(db):
    db.add(m.Setting(key="ai_cache:private", value={"secret_profile": "not public"}))
    db.commit()
    assert "ai_cache:private" not in service.get_settings(db)
    assert service.save_settings(db, {"auto_apply": {"enabled": True, "providers": ["greenhouse"]}})["auto_apply"]["enabled"]
    for payload in [{"auto_apply": {"enabled": True, "providers": []}}, {"auto_apply": {"enabled": True, "providers": ["unsupported"]}}, {"ai_monthly_budget_usd": 4}]:
        with pytest.raises(ValueError):
            service.save_settings(db, payload)
        db.rollback()


def test_empty_analytics_no_fake_rates_and_sources_do_not_inflate_jobs(db):
    assert service.analytics(db)["health"]["success_rate"] is None
    assert service.analytics(db)["summary"]["description_coverage"] is None
    assert service.dashboard(db)["top_opportunities"] == []
    board = source(db)
    ingest(db, board)
    listed = service.list_opportunities(db, q="Example", page=1, page_size=20)
    assert listed["total"] == 1 and listed["facets"]["role_family"][0]["name"] == "SWE"
    assert service.analytics(db)["summary"]["description_coverage"] == 1
    assert service.dashboard(db)["stats"]["new_opportunities"] == 1


def test_seed_idempotent_no_jobs_or_personal_facts(db):
    seed.seed_database(db)
    companies = db.scalar(select(func.count()).select_from(m.Company))
    sources = db.scalar(select(func.count()).select_from(m.CompanySource))
    result = seed.seed_database(db)
    assert result["companies_added"] == result["sources_added"] == 0
    assert db.scalar(select(func.count()).select_from(m.Company)) == companies
    assert db.scalar(select(func.count()).select_from(m.CompanySource)) == sources
    assert db.scalar(select(func.count()).select_from(m.Opportunity)) == 0
    assert service.get_profile(db)["skills"] == []


def test_source_identity_unique_constraint(db):
    board = source(db)
    ingest(db, board)
    appearance = db.scalar(select(m.JobSource))
    db.add(m.JobSource(company_source_id=board.id, opportunity_id=appearance.opportunity_id, external_id=appearance.external_id))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_source_holder_not_counted_as_employer(db):
    holder = m.Company(name="Discovery feeds", metadata_json={"source_holder": True})
    employer = m.Company(name="Real employer", metadata_json={})
    db.add_all([holder, employer])
    db.commit()
    assert service.list_companies(db)["total"] == 1
    assert service.dashboard(db)["stats"]["companies"] == 1
    assert service.analytics(db)["summary"]["companies"] == 1
    assert service.company_detail(db, holder.id) is None


def test_profile_undo_uses_restored_evaluation_history(db):
    board = source(db)
    ingest(db, board)
    service.save_profile(db, {"skills": ["python"], "preferred_roles": ["SWE"], "preferred_locations": ["Bangalore"]})
    before = only_op(db).fit_score
    service.save_profile(db, {"skills": ["python", "sql"]})
    last = db.scalar(select(m.Activity).where(m.Activity.kind == "profile.updated").order_by(m.Activity.created_at.desc()).limit(1))
    assert only_op(db).fit_score != before
    service.undo_activity(db, last.id)
    serialized = service.get_opportunity(db, only_op(db).id)
    assert serialized["fit_score"] == before
    assert serialized["evaluation"]["fit_score"] == before


def test_postgresql_schema_compiles():
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateTable, CreateIndex
    dialect = postgresql.dialect()
    for table in Base.metadata.sorted_tables:
        assert "CREATE TABLE" in str(CreateTable(table).compile(dialect=dialect))
        for index in table.indexes:
            assert "CREATE INDEX" in str(CreateIndex(index).compile(dialect=dialect))


def test_exclusivity_counts_source_membership_not_duplicate_appearances(db):
    board = source(db)
    original = job()
    mirror = job("mirror", canonical_url=original["canonical_url"], requisition_id=original["requisition_id"])
    ingest(db, board, [original, mirror])
    result = service.analytics(db)
    assert result["summary"]["canonical_opportunities"] == 1
    assert result["summary"]["source_appearances"] == 2
    assert result["sources"][0]["unique_jobs"] == 1
    assert result["sources"][0]["observed_exclusive"] == 1
    second = source(db, provider="capture", verified=False)
    ingest(db, second, [original], complete=False)
    result = service.analytics(db)
    assert all(s["observed_exclusive"] == 0 for s in result["sources"])
    assert sum(s["unique_jobs"] for s in result["sources"]) == 2


def test_india_analytics_scopes_counts_charts_and_sources_together(db):
    board = source(db)
    ingest(db, board, [job('india'),job('us',location='San Francisco, CA'),job('artist',title='3D Artist Intern')])
    scoped = service.analytics(db, scope='india')
    assert scoped['summary']['new_opportunities'] == 1
    assert scoped['summary']['raw_collected_records'] == 3
    assert scoped['sources'][0]['count'] == 1
    assert scoped['summary']['source_appearances'] == 1
    assert sum(x['count'] for x in scoped['daily_discoveries']) == 1
    assert all('San Francisco' not in x['name'] for x in scoped['locations'])
    assert service.analytics(db, scope='all')['summary']['new_opportunities'] == 3


def test_cadence_settings_propagate_and_undo_respects_overrides(db):
    priority = source(db)
    priority.priority = 1
    normal = source(db, provider="lever")
    custom = source(db, provider="ashby")
    custom.config = {"cadence_override": True}
    custom.cadence_hours = 48
    aggregate = source(db, provider="unstop")
    aggregate.priority = 1
    db.commit()
    service.save_settings(db, {"priority_poll_hours": 8, "normal_poll_hours": 24})
    assert priority.cadence_hours == 8
    assert normal.cadence_hours == 24
    assert aggregate.cadence_hours == 24
    assert custom.cadence_hours == 48
    activity = db.scalar(select(m.Activity).where(m.Activity.kind == "settings.updated").order_by(m.Activity.created_at.desc()))
    service.undo_activity(db, activity.id)
    assert priority.cadence_hours == 6
    assert normal.cadence_hours == aggregate.cadence_hours == 12
    assert custom.cadence_hours == 48


def test_known_seed_company_and_source_association_are_separate(db):
    seed.seed_database(db)
    company = db.scalar(select(m.Company).where(m.Company.verified.is_(True)))
    assert company is not None and company.metadata_json["seed"] is True
    candidate_source = db.scalar(select(m.CompanySource).where(m.CompanySource.verified.is_(False)))
    assert candidate_source is not None
    assert candidate_source.company.verified is True
    platform = source(db, provider="freehire", name="Discovery source", verified=False)
    ingest(db, platform, [job(company_name="Unverified startup", company_domain="startup.test")], complete=False, coverage_scope="discovery")
    employer = db.scalar(select(m.Company).where(m.Company.name == "Unverified startup"))
    assert employer.verified is False


def test_saved_refresh_plan_is_bounded_and_unchanged_read_updates_detail_clock(db):
    board = source(db)
    ingest(db, board, [job("a"), job("b")])
    appearances = db.scalars(select(m.JobSource).order_by(m.JobSource.external_id)).all()
    for appearance in appearances:
        appearance.opportunity.saved = True
        appearance.last_detail_checked = utcnow() - timedelta(days=2)
    db.commit()
    plans = service.saved_refresh_candidates(db, limit=1)
    assert len(plans) == 1
    assert len(plans[0]["config"]["refresh_jobs"]) == 1
    target = plans[0]["config"]["refresh_jobs"][0]
    assert target["canonical_url"] and target["company_name"] == "Example Labs"
    before = db.scalar(select(func.count()).select_from(m.Snapshot))
    result = ingest(db, board, [job(target["external_id"])], complete=True, coverage_scope="targeted")
    assert result["complete"] is False
    assert result["unchanged"] == 1
    assert db.scalar(select(func.count()).select_from(m.Snapshot)) == before
    remaining = service.saved_refresh_candidates(db)
    assert len(remaining[0]["config"]["refresh_external_ids"]) == 1
    assert target["external_id"] not in remaining[0]["config"]["refresh_external_ids"]


def test_saved_refresh_honors_disabled_sources_and_failure_backoff(db):
    board = source(db)
    ingest(db, board)
    appearance = db.scalar(select(m.JobSource))
    appearance.opportunity.saved = True
    appearance.last_detail_checked = None
    board.enabled = False
    db.commit()
    assert service.saved_refresh_candidates(db) == []
    board.enabled = True
    board.consecutive_failures = 2
    board.last_checked = utcnow()
    db.commit()
    assert service.saved_refresh_candidates(db) == []


def test_india_filter_includes_country_and_known_city_but_not_indiana(db):
    board = source(db)
    ingest(db, board, [job("in", location="", country="IN"), job("blr", location="Bengaluru"),
                       job("us", location="Indianapolis, Indiana", country="US"), job("remote", location="Remote", country=None)])
    result = service.list_opportunities(db, location="India", kind="internship")
    assert result["total"] == 2
    assert {x["sources"][0]["external_id"] for x in result["items"]} == {"in", "blr"}


def test_sparse_unknown_mode_preserved_but_removed_fee_evidence_clears_risk(db):
    board = source(db)
    ingest(db, board, [job(work_mode="remote", description="Software intern requires a training fee.")])
    assert only_op(db).risk_reasons
    ingest(db, board, [job(work_mode="unknown", description="")])
    assert only_op(db).work_mode == "remote" and only_op(db).risk_reasons
    ingest(db, board, [job(work_mode="unknown")])
    assert only_op(db).work_mode == "remote" and only_op(db).risk_reasons == []
