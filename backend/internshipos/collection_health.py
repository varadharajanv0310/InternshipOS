"""Inspect collection timeliness without contacting external schedulers."""
from datetime import timedelta
from sqlalchemy import select

from .db import aware, utcnow
from .models import CompanySource, Setting
from .source_health import health, _timestamp


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
    result = value.get('result') if isinstance(value.get('result'), dict) else {}
    failed = result.get('status') == 'failed' or bool(result.get('worker_errors'))
    sources = db.scalars(select(CompanySource).where(CompanySource.enabled.is_(True))).all()
    states = [health(source, now) for source in sources]
    counts = {}
    for state in states:
        counts[state['label']] = counts.get(state['label'], 0) + 1
    return {
        'status': 'failed' if failed else 'not_checked' if not stamp else 'late' if overdue else 'on_time',
        'last_finished_at': stamp,
        'expected_interval_hours': interval,
        'expected_next_at': expected,
        'late': overdue,
        'hours_since_finish': round(max(0.0, (now - stamp).total_seconds() / 3600), 2) if stamp else None,
        'enabled_sources': len(states),
        'due_sources': sum(state['due'] for state in states),
        'stale_sources': sum(state['stale'] for state in states),
        'awaiting_retry_sources': sum(state['backoff'] for state in states),
        'never_checked_sources': sum(not state['board_checked_at'] for state in states),
        'health_counts': counts,
        'last_result_boards': result.get('boards'),
        'detail': 'Scheduled triggers can arrive late. Source-level timestamps show which inventories were actually checked.',
    }
