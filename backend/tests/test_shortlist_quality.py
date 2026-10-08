"""Evidence boundaries, persistent choices and non-destructive mirror repair."""
from datetime import timedelta

import pytest
from sqlalchemy import event, func, select

from internshipos import domain, models as m, service
from internshipos.db import utcnow
from internshipos.shortlist import assessment, exclusions
from test_domain import db, source, job, ingest, only_op


def interpreted(text, profile):
    return domain.evaluate({"requirements": domain.extract_requirements(text)}, profile)


def test_explicit_degree_conflict_and_higher_degree_alternative():
    assert interpreted("Ph.D degree required.", {"education": {"degree": "B.Tech"}})["eligibility"] == "probably ineligible"
    checks = interpreted("Bachelor degree or higher required.", {"education": {"degree": "Master"}})["eligibility_checks"]
    assert checks[0]["result"] == "met"
    assert "confirmed degree" in checks[0]["reason"]


def test_degree_preferred_not_hard_exclusion_and_current_enrollment_unknown():
    assert interpreted("Master degree preferred.", {"degree": "B.Tech"})["eligibility"] == "unclear"
    result = interpreted("Currently pursuing a bachelor degree required.", {"degree": "B.Tech"})
    assert result["eligibility"] == "unclear"
    assert any(c["type"] == "enrollment_status" and c["result"] == "unknown" for c in result["eligibility_checks"])


def test_explicit_subject_requirement_uses_confirmed_branch():
    result = interpreted("Bachelor degree in computer science required.", {"education": {"degree": "B.Tech", "branch": "ECE"}})
    assert result["eligibility"] == "probably ineligible"
    assert interpreted("Bachelor degree in computer science required.", {"education": {"degree": "B.Tech", "branch": "CSE"}})["eligibility"] == "probably eligible"


def test_discrete_graduation_cohorts_not_unstated_range():
    assert interpreted("Graduation class of 2026 or 2028 required.", {"graduation_year": 2027})["eligibility"] == "probably ineligible"
    assert interpreted("Graduation year 2026 to 2028 required.", {"graduation_year": 2027})["eligibility"] == "probably eligible"


def test_explicit_availability_with_missing_fact_or_mismatch():
    text = "Available for 6 months required. Must start by 2026-12-01."
    result = interpreted(text, {"availability": {"months": 3, "start_date": "2026-12-10"}})
    assert result["eligibility"] == "probably ineligible"
    assert {c["result"] for c in result["eligibility_checks"]} == {"not_met"}
    missing = interpreted(text, {})
    assert missing["eligibility"] == "unclear" and missing["eligibility_reasons"]


def test_skill_mentions_are_not_requirements_and_missing_skill_is_unknown():
    assert not domain.extract_requirements("Our software team uses Python and SQL.")
    result = interpreted("Must have Python and SQL.", {"skills": ["python"]})
    assert result["eligibility"] == "unclear"
    assert "do not prove" in result["eligibility_reasons"][0]
    assert interpreted("Knowledge of Python or Java required.", {"skills": ["python"]})["eligibility"] == "probably eligible"
    assert domain.evaluate({"requirements":[{"type":"required_skills","skills":["js"],"match":"all"}]},{"skills":["JavaScript"]})["eligibility"] == "probably eligible"


def test_sparse_listings_do_not_refresh_description_clock(db):
    board = source(db); ingest(db, board)
    op = only_op(db)
    old = (utcnow() - timedelta(days=10)).isoformat()
    op.data = {**op.data, "description_checked_at": old}
    db.commit()
    ingest(db, board, [job(description="")])
    result = service.get_opportunity(db, op.id)
    assert result["shortlist"]["detail_checked_at"] == old.replace("+00:00", "Z")
    assert result["shortlist"]["listing_seen_at"]
    assert result["shortlist"]["state"] == "review" and op.eligibility != "probably ineligible"
    assert not service.dashboard(db)["top_opportunities"]
    with pytest.raises(ValueError, match="description is older"):
        service.create_application(db, {"opportunity_id": op.id})


def test_unchanged_real_description_refreshes_its_own_clock(db):
    board=source(db);ingest(db,board);op=only_op(db)
    op.data={**op.data,"description_checked_at":(utcnow()-timedelta(days=10)).isoformat()};db.commit()
    ingest(db,board)
    assert service.get_opportunity(db,op.id)["shortlist"]["preparation_allowed"]


def test_unverified_mirror_cannot_refresh_official_description_clock(db):
    board=source(db);ingest(db,board);op=only_op(db)
    old=(utcnow()-timedelta(days=10)).isoformat();op.data={**op.data,"description_checked_at":old};db.commit()
    mirror=source(db,provider="capture",verified=False);ingest(db,mirror,complete=False)
    assert op.data["description_checked_at"]==old


def test_role_and_company_exclusions_restore_independently_everywhere(db):
    board=source(db);ingest(db,board,[job("one"),job("two")]);ops=db.scalars(select(m.Opportunity).order_by(m.Opportunity.title,m.Opportunity.id)).all()
    app=service.create_application(db,{"opportunity_id":ops[0].id})
    service.set_shortlist_exclusion(db,{"kind":"opportunity","id":ops[0].id,"excluded":True})
    assert service.list_opportunities(db)["total"]==1
    assert service.analytics(db)["summary"]["canonical_opportunities"]==1
    service.set_shortlist_exclusion(db,{"kind":"company","id":board.company_id,"excluded":True})
    assert service.list_opportunities(db)["total"]==0 and service.dashboard(db)["top_opportunities"]==[]
    assert service.analytics(db)["summary"]["canonical_opportunities"]==0
    assert service.list_applications(db)["items"][0]["id"]==app["id"]
    with pytest.raises(ValueError,match="excluded"):
        service.create_application(db,{"opportunity_id":ops[1].id})
    service.set_shortlist_exclusion(db,{"kind":"company","id":board.company_id,"excluded":False})
    assert service.list_opportunities(db)["total"]==1
    service.set_shortlist_exclusion(db,{"kind":"opportunity","id":ops[0].id,"excluded":False})
    assert service.list_opportunities(db)["total"]==2


def test_exact_trusted_requisition_associates_official_boards(db):
    a=source(db);b=source(db,provider="workday")
    ingest(db,a)
    ingest(db,b,[job("mirror",requisition_id="req-j1",canonical_url="https://workday.example.test/job/JR1")])
    assert db.scalar(select(func.count()).select_from(m.Opportunity))==1
    assert db.scalar(select(func.count()).select_from(m.JobSource))==2
    assert db.scalar(select(m.IdentityDecision)).decision=="exact_requisition"


@pytest.mark.parametrize("variant",["unverified","different_employer","different_requisition","same_board"])
def test_requisition_claim_does_not_merge_unsupported_identity(db,variant):
    a=source(db);ingest(db,a)
    b=a if variant=="same_board" else source(db,provider="workday",verified=variant!="unverified")
    kwargs={"canonical_url":"https://other.example.test/job/role","requisition_id":"req-j1"}
    if variant=="different_employer":kwargs["company_name"]="A distinct subsidiary"
    if variant=="different_requisition":kwargs["requisition_id"]="req-j2"
    ingest(db,b,[job("mirror",**kwargs)])
    assert db.scalar(select(func.count()).select_from(m.Opportunity))==2


def test_reconciliation_dry_run_and_history_preservation(db):
    a=source(db);ingest(db,a);original=only_op(db)
    b=source(db,provider="capture",verified=False)
    ingest(db,b,[job("mirror",canonical_url="https://another.example.test/job/role",requisition_id="req-j1")],complete=False)
    mirror=db.scalar(select(m.Opportunity).where(m.Opportunity.id!=original.id))
    app=service.create_application(db,{"opportunity_id":mirror.id})
    mirror.canonical_url=original.canonical_url;db.commit()
    tables=(m.Opportunity,m.JobSource,m.Snapshot,m.Evidence,m.Application)
    before={table.__tablename__:db.scalar(select(func.count()).select_from(table)) for table in tables}
    dry=service.reconcile_shortlist_quality(db)
    assert dry["aliases_added"]==1 and not mirror.data.get("duplicate_of")
    applied=service.reconcile_shortlist_quality(db,apply=True);db.commit()
    assert applied["aliases_added"]==1 and mirror.data["duplicate_of"]==original.id
    assert {table.__tablename__:db.scalar(select(func.count()).select_from(table)) for table in tables}==before
    assert db.get(m.Application,app["id"]).opportunity_id==mirror.id
    assert service.list_opportunities(db)["total"]==1
    assert len(service.get_opportunity(db,original.id)["sources"])==2
    analytics=service.analytics(db)
    assert analytics["summary"]["canonical_opportunities"]==1 and analytics["summary"]["source_appearances"]==2
    assert sum(x["unique_jobs"] for x in analytics["sources"])==2
    assert service.reconcile_shortlist_quality(db,apply=True)["aliases_added"]==0
    service.reverse_shortlist_alias(db,mirror.id);db.commit()
    assert service.list_opportunities(db)["total"]==2
    assert service.reconcile_shortlist_quality(db,apply=True)["aliases_added"]==0


def test_generic_numeric_ids_without_explicit_requisition_key_not_mirrors(db):
    a=source(db);b=source(db,provider="workday")
    ingest(db,a,[job("a",requisition_id="42",raw={"id":42})])
    ingest(db,b,[job("b",requisition_id="42",raw={"id":42})])
    assert db.scalar(select(func.count()).select_from(m.Opportunity))==2
    assert service.reconcile_shortlist_quality(db)["aliases_added"]==0


def test_url_mirror_group_cannot_bridge_conflicting_requisitions(db):
    a=source(db);ingest(db,a,[job("a",requisition_id=None),job("b",requisition_id="req-b"),job("c",requisition_id="req-c")])
    ops=db.scalars(select(m.Opportunity).order_by(m.Opportunity.first_seen)).all()
    for op in ops:op.canonical_url="https://careers.example.test/job/common"
    db.commit()
    report=service.reconcile_shortlist_quality(db)
    assert report["aliases_added"]==1


def test_legacy_description_clock_recovers_observation_not_current_time(db):
    a=source(db);ingest(db,a);op=only_op(db)
    evidence=db.scalar(select(m.Evidence).where(m.Evidence.field=="description"))
    snap=db.get(m.Snapshot,evidence.snapshot_id);old=utcnow()-timedelta(days=20);snap.created_at=old
    op.data={k:v for k,v in op.data.items() if k not in {"description_checked_at","description_source_id"}};db.commit()
    report=service.reconcile_shortlist_quality(db,apply=True)
    assert report["description_clocks_recovered"]==1
    assert op.data["description_checked_at"]==old.isoformat().replace("+00:00","Z")


def test_historical_workday_location_id_flagged_without_deletion(db):
    a=source(db,provider="workday")
    ingest(db,a,[job("Chennai, India",requisition_id="Chennai, India",raw={"externalPath":"/job/Chennai/Software-Intern_JR123","bulletFields":["Chennai, India","JR123"]})])
    op=only_op(db);report=service.reconcile_shortlist_quality(db,apply=True)
    assert report["identity_review"] and op.data["identity_review"]
    assert db.scalar(select(m.JobSource)).external_id=="Chennai, India"
    assert not assessment(op,op.sources,exclusions(db))["recommended"]


def test_bounded_reconciliation_preserves_outside_page_canonical_and_batch_reads(db):
    a=source(db);ingest(db,a,[job(str(i)) for i in range(20)])
    ops=db.scalars(select(m.Opportunity).order_by(m.Opportunity.first_seen,m.Opportunity.id)).all()
    ops[-1].canonical_url=ops[0].canonical_url;ops[-1].requisition_id=ops[0].requisition_id;db.commit()
    reads=[]
    def capture(connection,cursor,statement,parameters,context,executemany):
        if statement.lstrip().upper().startswith('SELECT'):reads.append(statement)
    event.listen(db.bind,'before_cursor_execute',capture)
    try:report=service.reconcile_shortlist_quality(db,opportunity_ids=[ops[-1].id],limit=1,apply=True)
    finally:event.remove(db.bind,'before_cursor_execute',capture)
    assert report['target_count']==1 and report['evaluated']==1 and report['related_candidates']==19
    assert report['mirror_groups'][0]['canonical_id']==ops[0].id
    assert len(reads)<25, f'Unexpected per-record reads: {len(reads)}'


def test_old_queue_approval_is_rechecked_without_rewriting_history(db):
    from internshipos import application_queue, resumes
    a=source(db);ingest(db,a);op=only_op(db)
    app=service.create_application(db,{'opportunity_id':op.id})
    resume=m.Resume(name='Test-only');db.add(resume);db.flush()
    version=m.ResumeVersion(resume_id=resume.id,status='approved',data={});db.add(version);db.flush()
    application=db.get(m.Application,app['id']);application.resume_version_id=version.id
    db.add(m.Setting(key='auto_apply',value={'enabled':False,'providers':['greenhouse'],'daily_limit':5}));db.commit()
    application_queue.approve(db,application.id,eligibility_reviewed=True)
    prior=dict(application.data['auto_apply'])
    op.data={**op.data,'description_checked_at':(utcnow()-timedelta(days=10)).isoformat()};db.commit()
    assert not application_queue.listing(db)['items'][0]['approval_current']
    with pytest.raises(ValueError,match='description is older'):
        application_queue.approve(db,application.id,eligibility_reviewed=True)
    assert application.data['auto_apply']==prior
    assert resumes.preparation_pack(db,application.id)['ready_to_prepare'] is False
