"""Coverage certificates and stable employer identity protect actual history."""
from datetime import timedelta
from sqlalchemy import select
from internshipos import models as m,service
from internshipos.db import utcnow
from internshipos.source_health import health
from test_domain import db,source,job,ingest


def test_proven_listing_can_advance_absence_while_descriptions_rotate(db):
    board=source(db);ingest(db,board,[job('a'),job('b')])
    result=service.ingest_batch(db,board.id,[job('a')],complete=False,
        inventory_complete=True,error='detail_limit_reached',observed_count=1)
    missing=db.scalar(select(m.JobSource).where(m.JobSource.external_id=='b'))
    assert result['status']=='partial' and result['complete'] and missing.missed_complete_runs==1
    assert board.config['board_health']['inventory_complete'] is True
    assert board.config['board_health']['description_complete'] is False


def test_listing_certificate_cannot_override_fetch_page_or_identity_failures(db):
    board=source(db);ingest(db,board,[job('a'),job('b')])
    for error in ('detail_fetch_failed: http_error: HTTP 403','page_limit_reached','collection_time_budget_exhausted'):
        result=service.ingest_batch(db,board.id,[job('a')],complete=False,inventory_complete=True,error=error)
        assert not result['complete']
    missing=db.scalar(select(m.JobSource).where(m.JobSource.external_id=='b'))
    assert missing.missed_complete_runs==0


def test_successful_filtered_scan_remains_distinct_from_full_board_closure(db):
    board=source(db);ingest(db,board,[job('a'),job('b')])
    result=service.ingest_batch(db,board.id,[job('a')],complete=True,inventory_complete=True,coverage_scope='query')
    assert result['status']=='scoped_complete' and not result['complete']
    assert db.scalar(select(m.JobSource).where(m.JobSource.external_id=='b')).missed_complete_runs==0
    assert board.config['board_health']['inventory_complete'] and not board.config['board_health']['full_inventory']


def test_saved_detail_refresh_does_not_hide_failed_board_or_reset_backoff(db):
    board=source(db);ingest(db,board)
    service.ingest_batch(db,board.id,[],complete=False,error='http_error: HTTP 404')
    clock=board.config['board_checked_at'];prior=dict(board.config['board_health'])
    service.ingest_batch(db,board.id,[job()],complete=False,coverage_scope='targeted')
    assert board.config['board_checked_at']==clock and board.config['board_health']==prior
    assert health(board)['label']=='Broken'
    service.ingest_batch(db,board.id,[],complete=False,error='http_error: HTTP 404')
    assert board.config['board_health']['consecutive_failures']==2
    assert board.config['board_health']['last_success']==prior['last_success']


def test_global_feed_preserves_same_employer_when_duplicate_name_row_appears(db):
    board=source(db,provider='linkedin',name='Discovery feeds',domain_name=None,verified=False)
    role=job(company_name='Exact Employer',company_domain=None)
    ingest(db,board,[role],coverage_scope='discovery')
    appearance=db.scalar(select(m.JobSource));original_id=appearance.opportunity.company_id
    db.add(m.Company(name='Exact Employer',domain='official.example.com',verified=True));db.commit()
    result=ingest(db,board,[role],coverage_scope='discovery')
    assert result['invalid']==0 and appearance.opportunity.company_id==original_id
    changed=ingest(db,board,[{**role,'company_name':'Unrelated Employer'}],coverage_scope='discovery')
    assert changed['invalid']==1 and appearance.opportunity.company_id==original_id


def test_sparse_generic_intern_preserves_jd_classification_without_freshening_it(db):
    board=source(db); role=job(title='Intern',description='Software engineering internship: develop Python APIs and backend software.')
    ingest(db,board,[role]); appearance=db.scalar(select(m.JobSource)); prior=appearance.last_detail_checked
    assert appearance.opportunity.role_family=='SWE'
    result=ingest(db,board,[{**role,'description':'','description_html':''}])
    assert result['invalid']==0 and appearance.opportunity.role_family=='SWE'
    assert appearance.opportunity.opportunity_type=='internship'
    assert appearance.opportunity.description==role['description'] and appearance.last_detail_checked==prior


def test_checkpoint_metadata_and_board_observation_commit_together(db):
    board=source(db); board.config={'owner_setting':'keep'}; db.commit()
    metadata={'next_detail_cursor':7,'next_listing_cursor':20,'next_retained_detail_cursor':3}
    result=ingest(db,board,collection_metadata=metadata)
    assert board.config['owner_setting']=='keep' and board.config['detail_cursor']==7
    assert board.config['listing_cursor']==20 and board.config['retained_detail_cursor']==3
    assert db.get(m.FetchRun,result['run_id']).data['collection']==metadata
