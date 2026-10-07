"""Health never substitutes saved-detail success for board coverage."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from internshipos.db import Base
from internshipos.models import Company, CompanySource, Setting
from internshipos.source_health import budget_only, health, timing
from internshipos.collection_health import collection_health

NOW = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)


def source(**changes):
    fields = dict(config={}, last_checked=NOW, last_success=NOW, last_error=None,
                  consecutive_failures=0, cadence_hours=6, status='complete',
                  enabled=True, verified=True)
    fields.update(changes)
    return SimpleNamespace(**fields)


def test_fast_source_stale_before_old_24_hour_floor():
    state = health(source(last_checked=NOW-timedelta(hours=13)), NOW)
    assert state['stale'] is True and state['freshness'] == 'Stale'
    assert state['due'] is True and state['overdue_hours'] == 7
    assert state['next_due_at'] == NOW-timedelta(hours=7)


def test_due_and_stale_have_separate_meanings():
    state = health(source(last_checked=NOW-timedelta(hours=7)), NOW)
    assert state['due'] is True and state['stale'] is False
    assert state['freshness'] == 'Due'


def test_long_cadence_does_not_become_stale_after_one_day():
    state = health(source(last_checked=NOW-timedelta(hours=80), cadence_hours=72), NOW)
    assert state['due'] is True and state['stale'] is False


def test_saved_detail_read_cannot_refresh_board_clock_or_claim_success():
    old = NOW-timedelta(hours=30)
    state = health(source(config={'board_checked_at': old.isoformat()},
                         last_checked=NOW, last_success=NOW), NOW)
    assert state['board_checked_at'] == old
    assert state['last_success'] is None
    assert state['stale'] is True


def test_board_snapshot_survives_targeted_refresh_status_and_backoff():
    old = NOW-timedelta(hours=13)
    board = {'status': 'complete', 'last_error': None, 'last_success': old.isoformat(),
             'consecutive_failures': 0, 'full_inventory': True, 'coverage_scope': 'full'}
    state = health(source(config={'board_checked_at': old.isoformat(), 'board_health': board},
                         status='error', last_error='HTTP 403', consecutive_failures=6), NOW)
    assert state['label'] == 'Successful'
    assert state['last_success'] == old and state['full_inventory'] is True
    assert state['due'] is True and state['retry_hours'] == 0


@pytest.mark.parametrize('issue,code,label', [
    ('page_limit_reached; HTTP 429: rate limited', 'rate_limited', 'Blocked'),
    ('detail_limit_reached; HTTP 403', 'access_blocked', 'Blocked'),
    ('HTTP 404; page_limit_reached', 'address_changed', 'Broken'),
    ('collection_time_budget_exhausted; request timed out', 'temporary_failure', 'Broken'),
    ('inventory_incomplete; invalid JSON response', 'parser_or_scope', 'Broken'),
])
def test_mixed_budget_error_is_not_hidden_by_partial_status(issue, code, label):
    state = health(source(status='partial', last_error=issue), NOW)
    assert state['label'] == label and state['issue_code'] == code
    assert state['action']
    assert budget_only(issue) is False


def test_budget_only_error_is_actionable_partial_without_backoff():
    state = health(source(status='partial', last_error='page_limit_reached; detail_limit_reached'), NOW)
    assert state['label'] == 'Partial' and state['issue_code'] == 'unfinished_scan'
    assert state['retry_hours'] == 0
    assert budget_only('page_limit_reached;') is True
    assert budget_only('') is False


def test_failure_backoff_does_not_hide_old_inventory():
    state = health(source(last_checked=NOW-timedelta(hours=13), status='error',
                         last_error='HTTP 429', consecutive_failures=6), NOW)
    assert state['stale'] is True and state['backoff'] is True
    assert state['due'] is False and state['retry_hours'] == 64
    assert state['next_due_at'] == NOW+timedelta(hours=51)


def test_paused_source_is_not_counted_as_due_or_stale():
    state = health(source(enabled=False, last_checked=NOW-timedelta(days=10)), NOW)
    assert state['freshness'] == 'Paused'
    assert not state['stale'] and not state['due'] and not state['backoff']


def test_complete_target_scope_does_not_claim_full_inventory():
    state = health(source(status='scoped_complete'), NOW)
    assert state['label'] == 'Successful (target scope)'
    assert state['full_inventory'] is False


def test_listing_and_description_completeness_are_explicit():
    board = {'status':'partial', 'last_error':'detail_limit_reached',
             'inventory_complete':True, 'description_complete':False, 'full_inventory':False}
    state = health(source(config={'board_checked_at':NOW.isoformat(),'board_health':board}),NOW)
    assert state['label'] == 'Partial'
    assert state['inventory_complete'] is True and state['description_complete'] is False
    assert state['full_inventory'] is False


def test_detail_404_does_not_recommend_replacing_successful_board():
    board = {'status':'error', 'last_error':'detail_fetch_failed: HTTP 404',
             'inventory_complete':True, 'description_complete':False, 'full_inventory':False}
    state = health(source(config={'board_checked_at':NOW.isoformat(),'board_health':board}),NOW)
    assert 'detail URLs' in state['action']
    assert 'board address' not in state['action']


def test_invalid_and_future_clock_are_due_without_crashing():
    assert timing(source(config={'board_checked_at':'invalid'}, last_checked=None), NOW)['due'] is True
    state = timing(source(last_checked=NOW+timedelta(days=1)), NOW)
    assert state['clock_issue'] is True and state['due'] is True


def test_worker_gap_and_due_backlog_are_visible_without_external_api():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        company = Company(name='Fixture employer'); db.add(company); db.flush()
        db.add_all([
            CompanySource(company_id=company.id, provider='fixture', url='https://example.test/1', enabled=True,
                          cadence_hours=6, status='complete', last_checked=NOW-timedelta(hours=13)),
            CompanySource(company_id=company.id, provider='fixture', url='https://example.test/2', enabled=True,
                          cadence_hours=6, status='error', last_checked=NOW-timedelta(hours=13),
                          last_error='HTTP 429', consecutive_failures=6),
            CompanySource(company_id=company.id, provider='fixture', url='https://example.test/3', enabled=False),
            Setting(key='worker_heartbeat', value={'at':(NOW-timedelta(hours=8)).isoformat(), 'result':{'boards':96}}),
        ]); db.commit()
        result = collection_health(db, NOW)
        assert result['status'] == 'late' and result['hours_since_finish'] == 8
        assert result['enabled_sources'] == 2 and result['due_sources'] == 1
        assert result['stale_sources'] == 2 and result['awaiting_retry_sources'] == 1
        assert result['last_result_boards'] == 96
        heartbeat = db.get(Setting,'worker_heartbeat')
        heartbeat.value = {'at':NOW.isoformat(),'result':{'status':'failed'}}; db.commit()
        assert collection_health(db,NOW)['status'] == 'failed'
        heartbeat.value = {'at':NOW.isoformat(),'result':{'boards':96,'worker_errors':1}}; db.commit()
        assert collection_health(db,NOW)['status'] == 'failed'
        heartbeat.value = {'at':NOW.isoformat(),'result':{'boards':96,'worker_errors':0}}; db.commit()
        assert collection_health(db,NOW)['status'] == 'on_time'
        heartbeat.value = {'at':NOW.isoformat(),'result':{'boards':3,'worker_errors':1}}; db.commit()
        assert collection_health(db,NOW)['status'] == 'failed'
    engine.dispose()


def test_never_reported_worker_does_not_appear_healthy():
    engine = create_engine('sqlite://'); Base.metadata.create_all(engine)
    with Session(engine) as db:
        assert collection_health(db,NOW)['status'] == 'not_checked'
    engine.dispose()


def test_listing_only_success_cannot_claim_full_description_coverage():
    board={'status':'scoped_complete','inventory_complete':True,'description_complete':False,
           'description_scope':'listing_only','description_target_count':4}
    state=health(source(config={'board_checked_at':NOW.isoformat(),'board_health':board}),NOW)
    assert state['label']=='Partial' and state['issue_code']=='descriptions_pending'
    assert state['description_target_count']==4 and state['description_scope']=='listing_only'


def test_inventory_that_changes_during_scan_requires_review():
    state=health(source(status='error',last_error='inventory_changed_during_scan; inventory_incomplete'),NOW)
    assert state['label']=='Needs review' and state['full_inventory'] is False
