"""Transport health is independent from completeness and employer association."""
from datetime import timedelta
from .db import aware,utcnow

BUDGET_ISSUES=('detail_limit_reached','page_limit_reached','request_budget_exhausted','job_limit_reached','collection_time_budget_exhausted','inventory_incomplete','workday_query_cap_requires_partitioning')

def budget_only(error):
    return bool(error) and all(any(part.strip()==x for x in BUDGET_ISSUES) for part in str(error).split(';'))

def health(source):
    issue=str(source.last_error or '')
    if source.status=='quarantined':label='Needs review'
    elif budget_only(issue) or source.status=='partial':label='Partial'
    elif any(x in issue for x in ['HTTP 401','HTTP 403','HTTP 406','HTTP 429','challenge_page']):label='Blocked'
    elif source.status=='error':label='Broken'
    elif not source.last_checked:label='Unverified' if not source.verified else 'Not checked'
    elif source.status=='complete':label='Successful'
    else:label='Unverified'
    stale=bool(source.last_checked and utcnow()-aware(source.last_checked)>timedelta(hours=max(24,source.cadence_hours*2)))
    return {'label':label,'stale':stale,'last_success':source.last_success,'issue':issue or None,'full_inventory':source.status=='complete'}
