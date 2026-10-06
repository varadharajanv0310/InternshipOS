"""Endpoint repair rollout cannot fake success or rewrite historical identities."""
from sqlalchemy import select
from internshipos.models import CompanySource, JobSource, FetchRun
from internshipos.source_repairs import apply_endpoint_repairs, retire_replaced_sources, backfill_scoped_health
from internshipos.source_health import health
from test_domain import db, source, ingest


def manifest(original, **changes):
    return {'observed_on':'2026-10-06', 'repairs':[{
        'company':original.company.name, 'from_provider':original.provider, 'from_url':original.url,
        'provider':'ashby', 'url':'https://jobs.ashbyhq.com/example', 'config':{'token':'example'},
        'evidence':{'kind':'official_site_ats_link','linked_from':'https://example.test/careers'},
        **changes}], 'existing_canonical_bindings':[]}


def replacement(db, old):
    return db.get(CompanySource, old.config['replacement_source_id'])


def test_new_endpoint_is_distinct_and_idempotent_with_historical_jobs(db):
    old = source(db); old.config = {'custom_owner_setting':True}; db.commit(); ingest(db,old)
    result = apply_endpoint_repairs(db, manifest(old))
    new = replacement(db,old)
    assert result == {'sources_added':1,'old_sources_linked':1}
    assert new.id != old.id and old.provider == 'greenhouse'
    assert new.status == 'pending' and new.last_checked is None and new.enabled
    assert old.config['custom_owner_setting'] and old.enabled
    assert db.scalar(select(JobSource)).company_source_id == old.id
    assert apply_endpoint_repairs(db, manifest(old)) == {'sources_added':0,'old_sources_linked':0}
    new.config = {**new.config, 'token':'owner-custom-token'}; db.commit()
    apply_endpoint_repairs(db,manifest(old))
    assert new.config['token'] == 'owner-custom-token'


def test_disabled_owner_source_stays_disabled_and_wrong_endpoint_is_not_matched(db):
    old = source(db); old.enabled = False; old.cadence_hours = 72; old.priority = 4; db.commit()
    apply_endpoint_repairs(db,manifest(old,from_url=old.url+'/wrong'))
    assert 'replacement_source_id' not in old.config
    apply_endpoint_repairs(db,manifest(old))
    new = replacement(db,old)
    assert not new.enabled and new.cadence_hours == 72 and new.priority == 4


def test_failed_or_targeted_replacement_cannot_retire_old_board(db):
    old = source(db); apply_endpoint_repairs(db,manifest(old)); new = replacement(db,old)
    ingest(db,new,complete=False,error='HTTP 403',inventory_complete=False)
    assert retire_replaced_sources(db,new.id) == 0 and old.enabled
    ingest(db,new,complete=True,coverage_scope='targeted')
    assert retire_replaced_sources(db,new.id) == 0 and old.enabled


def test_successful_inventory_retires_explicit_old_route_without_deleting_history(db):
    old = source(db); ingest(db,old); old.last_error='HTTP 404'; old.status='error'; db.commit()
    apply_endpoint_repairs(db,manifest(old)); new = replacement(db,old)
    ingest(db,new,jobs=[],complete=False,error='detail_limit_reached',inventory_complete=True)
    assert retire_replaced_sources(db,new.id) == 1
    assert not old.enabled and old.status == 'superseded' and old.last_error == 'HTTP 404'
    assert old.config['retired_health']['was_enabled']
    assert db.scalars(select(JobSource).where(JobSource.company_source_id==old.id)).first()
    assert db.scalars(select(JobSource).where(JobSource.company_source_id==old.id)).first().opportunity.status=='needs_recheck'
    assert health(old)['label'] == 'Superseded'
    assert 'https://jobs.ashbyhq.com/example' in health(old)['action']
    assert retire_replaced_sources(db,new.id) == 0


def test_canonical_binding_preserves_existing_source_and_owner_cadence(db):
    old = source(db,provider='generic')
    new = source(db,provider='workday'); new.cadence_hours=48; db.commit()
    data={'observed_on':'2026-10-06','repairs':[], 'existing_canonical_bindings':[{
        'company':old.company.name,'generic_url':old.url,'provider':new.provider,'url':new.url,
        'evidence':{'kind':'official_site_ats_link'}}]}
    apply_endpoint_repairs(db,data)
    assert old.config['replacement_source_id'] == new.id and new.cadence_hours == 48
    assert old.enabled and retire_replaced_sources(db,new.id) == 0


def test_historical_scope_correction_uses_persisted_proof_without_new_freshness(db):
    old = source(db); result=ingest(db,old,coverage_scope='query')
    clock=old.config['board_checked_at']; old.config={'board_checked_at':clock}
    old.status='partial'; db.commit()
    assert backfill_scoped_health(db) == 1
    assert old.status=='scoped_complete' and old.config['board_checked_at']==clock
    assert not old.config['board_health']['full_inventory']
    assert old.config['scope_label_correction']['fetch_run_id']==result['run_id']
    assert backfill_scoped_health(db)==0


def test_historical_scope_correction_rejects_unfinished_or_mismatched_check(db):
    old=source(db); result=ingest(db,old,complete=False,coverage_scope='query')
    old.config={'board_checked_at':old.config['board_checked_at']}; db.commit()
    assert backfill_scoped_health(db)==0
    run=db.get(FetchRun,result['run_id']); run.data={**run.data,'requested_complete':True}; db.commit()
    old.config={'board_checked_at':'2020-01-01T00:00:00+00:00'}; db.commit()
    assert backfill_scoped_health(db)==0 and old.status=='partial'


def test_superseded_source_cannot_keep_matched_role_active_after_current_closure(db):
    from internshipos.service import reconcile_availability
    old=source(db); ingest(db,old)
    apply_endpoint_repairs(db,manifest(old)); new=replacement(db,old)
    ingest(db,new)
    assert retire_replaced_sources(db,new.id)==1
    current=db.scalar(select(JobSource).where(JobSource.company_source_id==new.id))
    assert current.opportunity.status=='active'
    current.status='confirmed_closed'; db.flush()
    reconcile_availability(db,current.opportunity)
    assert current.opportunity.status=='confirmed_closed'
    assert db.scalar(select(JobSource).where(JobSource.company_source_id==old.id)).status=='active'


def test_owner_paused_source_remains_availability_evidence(db):
    from internshipos.service import reconcile_availability
    old=source(db); ingest(db,old); old.enabled=False; db.flush()
    appearance=db.scalar(select(JobSource))
    reconcile_availability(db,appearance.opportunity)
    assert appearance.opportunity.status=='active'
