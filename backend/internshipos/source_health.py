"""Board transport, completeness and freshness are separate observations.

Targeted saved-role refreshes must not make a board look newly collected. The
worker and API share ``timing`` so a displayed next check matches the due plan.
Internal timestamps are UTC datetimes; ``serialize.json_value`` encodes them.
"""
from datetime import datetime, timedelta
import re

from .db import aware, utcnow

BUDGET_ISSUES = (
    'detail_limit_reached', 'page_limit_reached', 'request_budget_exhausted',
    'job_limit_reached', 'collection_time_budget_exhausted', 'inventory_incomplete',
    'workday_query_cap_requires_partitioning',
)


def issue_parts(error):
    return [part.strip() for part in str(error or '').split(';') if part.strip()]


def budget_only(error):
    parts = issue_parts(error)
    return bool(parts) and all(part in BUDGET_ISSUES for part in parts)


def _timestamp(value):
    if isinstance(value, datetime):
        return aware(value)
    try:
        return aware(datetime.fromisoformat(str(value).replace('Z', '+00:00'))) if value else None
    except (ValueError, TypeError):
        return None


def board_observation(source):
    config = source.config or {}
    snapshot = config.get('board_health')
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    checked = _timestamp(config.get('board_checked_at')) or _timestamp(source.last_checked)
    success = _timestamp(snapshot.get('last_success')) if snapshot else _timestamp(source.last_success)
    # Historical targeted reads updated last_success. A later detail timestamp
    # cannot establish that the inventory succeeded at the older board check.
    if not snapshot and success and checked and success > checked:
        success = None
    return {
        'checked_at': checked,
        'last_success': success,
        'status': snapshot.get('status', source.status),
        'issue': str(snapshot.get('last_error', source.last_error) or ''),
        'consecutive_failures': snapshot.get('consecutive_failures', source.consecutive_failures) or 0,
        'coverage_scope': snapshot.get('coverage_scope', 'unknown'),
        'full_inventory': bool(snapshot.get('full_inventory', source.status == 'complete')),
        'inventory_complete': snapshot.get('inventory_complete'),
        'description_complete': snapshot.get('description_complete'),
        'snapshot_available': bool(snapshot),
    }


def timing(source, now=None):
    """Return UTC datetime due points shared by source UI and worker selection.

Failure backoff postpones the next permitted attempt but never conceals stale
coverage. Stale means over twice the source cadence, without a 24-hour floor.
"""
    now = aware(now or utcnow())
    observation = board_observation(source)
    checked = observation['checked_at']
    try:
        cadence = max(0.25, float(source.cadence_hours or 24))
    except (TypeError, ValueError):
        cadence = 24.0
    try:
        failures = max(0, int(observation['consecutive_failures']))
    except (TypeError, ValueError):
        failures = 0
    retry = min(72, 2 ** min(failures, 6)) if failures else 0
    interval = max(cadence, retry)
    clock_grace = min(1.0, max(0.25, cadence * 0.1))
    clock_issue = bool(checked and checked > now + timedelta(hours=clock_grace))
    next_due = checked + timedelta(hours=interval) if checked and not clock_issue else None
    expected = checked + timedelta(hours=cadence) if checked and not clock_issue else None
    enabled = source.enabled is not False
    due = enabled and (next_due is None or now >= next_due)
    stale = bool(enabled and (clock_issue or checked and now - checked > timedelta(hours=cadence * 2)))
    freshness = 'Paused' if not enabled else 'Clock issue' if clock_issue else 'Not checked' if not checked else 'Stale' if stale else 'Due' if due else 'Fresh'
    return {
        'board_checked_at': checked,
        'cadence_hours': cadence,
        'retry_hours': retry,
        'effective_interval_hours': interval,
        'next_due_at': next_due,
        'cadence_due_at': expected,
        'due': bool(due),
        'stale': stale,
        'freshness': freshness,
        'overdue_hours': round(max(0.0, (now - next_due).total_seconds() / 3600), 2) if next_due and enabled else 0,
        'backoff': bool(enabled and retry > cadence and next_due and now < next_due),
        'clock_issue': clock_issue,
    }


def classify_issue(error):
    """Mixed budget/transport failures retain the transport diagnosis."""
    parts = issue_parts(error)
    failures = [part for part in parts if part not in BUDGET_ISSUES]
    issue = '; '.join(failures).lower()
    if not parts:
        return None, None
    if not failures:
        return 'unfinished_scan', 'Continue the saved scan position; unfinished work is not a closed vacancy.'
    if re.search(r'http\s*429\b', issue) or any(x in issue for x in ('rate_limit', 'rate limit', 'too many requests')):
        return 'rate_limited', 'Wait for the retry window, then check again with fewer requests.'
    if re.search(r'http\s*(401|403|406)\b', issue) or any(x in issue for x in ('challenge_page', 'access denied', 'captcha', 'cloudflare', 'blocked by')):
        return 'access_blocked', 'Check the official public careers route or an available employer-supported feed. Access challenges need manual review.'
    if re.search(r'http\s*(404|410)\b', issue) or any(x in issue for x in ('board_not_found', 'tenant_not_found', 'board not found')):
        return 'address_changed', 'Verify the current board address against the employer’s official careers page.'
    if any(x in issue for x in ('timeout', 'timed out', 'connection', 'dns', 'name or service', 'temporary failure')) or re.search(r'http\s*5\d\d\b', issue):
        return 'temporary_failure', 'Retry after backoff; a failed request cannot establish that roles closed.'
    if any(x in issue for x in ('inventory loss', 'quarantin', 'reported inventory exceeds', 'storage filter omitted', 'external id changed employer', 'lacks employer identity')):
        return 'inventory_review', 'Compare the observed inventory with previous complete scans before accepting closures.'
    if 'response_size_limit_exceeded' in issue:
        return 'response_limit', 'Find the public structured feed or reduce its query scope while keeping the response-size safeguard.'
    if any(x in issue for x in ('requires_partitioning', 'unsupported', 'dynamic', 'javascript', 'no structured', 'no_public_jobposting', 'configured_feed', 'no_recognized_cards', 'parse', 'json', 'xml')):
        return 'parser_or_scope', 'Check the provider parser and supported query scope against the current public response.'
    return 'collection_failure', 'Inspect the latest fetch evidence and repair the source or provider before trusting its coverage.'


def health(source, now=None):
    observation = board_observation(source)
    status, issue = observation['status'], observation['issue']
    code, action = classify_issue(issue)
    superseded = (source.config or {}).get('replacement_state') == 'superseded'
    if observation['inventory_complete'] is True and observation['description_complete'] is False and code != 'unfinished_scan':
        # A missing description URL is not evidence that the board URL moved.
        action = 'The listing scope was checked, but some role descriptions were not. Recheck those detail URLs and retain the successful inventory observation.'
    if superseded:
        label = 'Superseded'
        action = 'Replaced after a successful listing check: ' + str(source.config.get('replacement_url') or '') + '. Historical errors and roles are preserved.'
    elif status == 'quarantined' or code == 'inventory_review':
        label = 'Needs review'
    elif code in ('rate_limited', 'access_blocked'):
        label = 'Blocked'
    elif issue and not budget_only(issue):
        label = 'Broken'
    elif budget_only(issue) or status == 'partial':
        label = 'Partial'
    elif not observation['checked_at']:
        label = 'Not checked' if source.verified else 'Unverified'
    elif status == 'scoped_complete':
        label = 'Successful (target scope)'
    elif status == 'complete':
        label = 'Successful'
    elif status == 'error':
        label = 'Broken'
    else:
        label = 'Unverified'
    return {
        'label': label,
        **timing(source, now),
        'last_success': observation['last_success'],
        'issue': issue or None,
        'issue_code': code,
        'action': action,
        'full_inventory': observation['full_inventory'],
        'inventory_complete': observation['inventory_complete'],
        'description_complete': observation['description_complete'],
        'coverage_scope': observation['coverage_scope'],
        'board_snapshot_available': observation['snapshot_available'],
    }
