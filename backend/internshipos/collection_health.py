"""Inspect collection timeliness without contacting external schedulers."""
from datetime import timedelta
import math
from sqlalchemy import select

from .db import aware, utcnow
from .models import CompanySource, Setting
from .source_health import health, _timestamp
from .jobs import WorkerLease, collection_limits


def collection_health(db, now=None):
    """Actual worker completion and enabled-source due counts, not cron promises."""
    now = aware(now or utcnow())
    heartbeat = db.get(Setting, 'worker_heartbeat')
    value = heartbeat.value if heartbeat and isinstance(heartbeat.value, dict) else {}
    stamp = _timestamp(value.get('at'))
    interval_setting = db.get(Setting, 'collection_worker_interval_hours')
    try:
        interval = max(0.25, float(interval_setting.value)) if interval_setting else 1.0
    except (TypeError, ValueError):
        interval = 1.0
    grace = min(1.0, max(0.25, interval * 0.5))
    expected = stamp + timedelta(hours=interval) if stamp else None
    overdue = bool(stamp and now > expected + timedelta(hours=grace))
    worker_result=value.get('result') if isinstance(value.get('result'),dict) else {}
    collection=db.get(Setting,'collection_last_run')
    collection_value=collection.value if collection and isinstance(collection.value,dict) else {}
    result=collection_value.get('result') if isinstance(collection_value.get('result'),dict) else worker_result
    collection_stamp=_timestamp(collection_value.get('at')) or (stamp if 'boards' in worker_result else None)
    failed = any(row.get('status')=='failed' or row.get('worker_errors') for row in (worker_result,result))
    behind = bool(result.get('run_budget_exhausted') and result.get('deferred_boards'))
    sources = db.scalars(select(CompanySource).where(CompanySource.enabled.is_(True))).all()
    states = [health(source, now) for source in sources]
    counts = {}
    for state in states:
        counts[state['label']] = counts.get(state['label'], 0) + 1
    limits=result.get('limits') if isinstance(result.get('limits'),dict) else collection_limits()
    lease=db.get(WorkerLease,'collection')
    lease_active=bool(lease and aware(lease.expires_at)>now)
    due=sum(state['due'] for state in states)
    collection_late=bool(due and collection_stamp and now>collection_stamp+timedelta(hours=interval)+timedelta(hours=grace))
    board_count=result.get('boards') or 0
    elapsed=result.get('elapsed_seconds') or 0
    source_limit=max(1,int(limits.get('source_limit',12)))
    return {
        'status': 'failed' if failed else 'not_checked' if not stamp else 'late' if overdue or collection_late else 'behind' if behind else 'on_time',
        'last_finished_at': stamp,
        'last_collection_finished_at': collection_stamp,
        'collection_late': collection_late,
        'expected_interval_hours': interval,
        'expected_next_at': expected,
        'late': overdue,
        'hours_since_finish': round(max(0.0, (now - stamp).total_seconds() / 3600), 2) if stamp else None,
        'enabled_sources': len(states),
        'due_sources': due,
        'stale_sources': sum(state['stale'] for state in states),
        'awaiting_retry_sources': sum(state['backoff'] for state in states),
        'never_checked_sources': sum(not state['board_checked_at'] for state in states),
        'health_counts': counts,
        'last_result_boards': result.get('boards'),
        'oldest_overdue_hours': max((state['overdue_hours'] for state in states if state['due']),default=0),
        'due_successful_sources': sum(state['due'] and state['label'] in ('Successful','Successful (target scope)') for state in states),
        'due_partial_sources': sum(state['due'] and state['label']=='Partial' for state in states),
        'due_failed_sources': sum(state['due'] and state['label'] in ('Broken','Blocked','Needs review') for state in states),
        'stale_successful_sources': sum(state['stale'] and state['label'] in ('Successful','Successful (target scope)') for state in states),
        'stale_partial_sources': sum(state['stale'] and state['label']=='Partial' for state in states),
        'stale_failed_sources': sum(state['stale'] and state['label'] in ('Broken','Blocked','Needs review') for state in states),
        'checks_requested_per_hour': round(sum(1/state['effective_interval_hours'] for state in states),2),
        'selection_limit_per_run': source_limit,
        'runs_to_clear_current_due_at_selection_limit': math.ceil(due/source_limit),
        'run_budget_seconds': limits.get('run_budget_seconds'),
        'collection_concurrency': limits.get('concurrency'),
        'last_run_elapsed_seconds': elapsed or None,
        'last_run_deferred_sources': result.get('deferred_boards',0),
        'last_run_budget_exhausted': bool(result.get('run_budget_exhausted')),
        'last_run_boards_per_minute': round(board_count*60/elapsed,2) if elapsed else None,
        'worker_active': lease_active,
        'worker_started_at': aware(lease.started_at) if lease_active else None,
        'worker_lease_expires_at': aware(lease.expires_at) if lease_active else None,
        'detail': 'Scheduled triggers can arrive late. Source-level timestamps show which inventories were actually checked.',
        'capacity_note': 'The selection ceiling is not guaranteed throughput. Sources that cannot fit the remaining run window stay due or queued; measured throughput includes source errors as completed attempts.',
    }
