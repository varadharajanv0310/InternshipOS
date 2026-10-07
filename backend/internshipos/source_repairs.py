"""Audited endpoint replacements preserve history and owner monitoring choices."""
import json
from pathlib import Path

from sqlalchemy import select

from .db import aware, utcnow
from .models import Activity, Company, CompanySource, FetchRun, JobSource, Opportunity


def apply_endpoint_repairs(db, manifest=None):
    if manifest is None:
        path = Path(__file__).parent / 'data/source_endpoint_repairs.json'
        manifest = json.loads(path.read_text(encoding='utf-8'))
    companies = {c.name.casefold(): c for c in db.scalars(select(Company)).all()}
    rows = db.scalars(select(CompanySource).order_by(CompanySource.id).with_for_update()
                      .execution_options(populate_existing=True)).all()
    index = {(r.company_id, r.provider, r.url): r for r in rows}
    added = linked = 0
    for repair in manifest.get('repairs', []):
        company = companies.get(repair['company'].casefold())
        if not company:
            continue
        urls = {repair['from_url'], *repair.get('from_urls', [])}
        originals = [index[(company.id, repair['from_provider'], url)] for url in urls
                     if (company.id, repair['from_provider'], url) in index]
        if not originals:
            continue
        key = (company.id, repair['provider'], repair['url'])
        replacement = index.get(key)
        if not replacement:
            # Create a distinct source identity across board/provider migrations.
            # Historical natural IDs and closure evidence stay on the old source.
            original = originals[0]
            replacement = CompanySource(company_id=company.id, provider=repair['provider'],
                url=repair['url'], config={}, verified=False,
                enabled=any(r.enabled for r in originals), priority=original.priority,
                cadence_hours=original.cadence_hours, status='pending')
            db.add(replacement); db.flush(); index[key] = replacement; added += 1
        evidence = repair['evidence']
        repair_key = manifest['observed_on'] + ':' + repair['from_provider'] + ':' + repair['from_url']
        # A once-only routing update leaves subsequent owner edits intact.
        if replacement.config.get('endpoint_repair_key') != repair_key:
            replacement.config = {**replacement.config, **repair.get('config', {}),
                'association_status':'verified', 'association_evidence':evidence,
                'endpoint_repair_key':repair_key}
            replacement.verified = True
        for original in originals:
            if original.id == replacement.id:
                continue
            if original.config.get('replacement_source_id') != replacement.id:
                original.config = {**original.config, 'replacement_source_id':replacement.id,
                    'replacement_url':replacement.url, 'replacement_evidence':evidence,
                    'replacement_state':'awaiting_live_inventory'}
                linked += 1
    for binding in manifest.get('existing_canonical_bindings', []):
        company = companies.get(binding['company'].casefold())
        if not company:
            continue
        original = index.get((company.id, 'generic', binding['generic_url']))
        replacement = index.get((company.id, binding['provider'], binding['url']))
        if not original or not replacement:
            continue
        if replacement.config.get('canonical_binding_evidence') != binding['evidence']:
            replacement.config = {**replacement.config, 'canonical_binding_evidence':binding['evidence'],
                'association_status':'verified', 'association_evidence':binding['evidence']}
            replacement.verified = True
        if original.config.get('replacement_source_id') != replacement.id:
            original.config = {**original.config, 'replacement_source_id':replacement.id,
                'replacement_url':replacement.url, 'replacement_evidence':binding['evidence'],
                'replacement_state':'awaiting_live_inventory'}
            linked += 1
    if added or linked:
        db.add(Activity(kind='registry.repaired', title='Verified source replacements installed',
            data={'sources_added':added, 'old_sources_linked':linked,
                  'evidence_date':manifest['observed_on']}))
    db.commit()
    return {'sources_added':added, 'old_sources_linked':linked}


def retire_replaced_sources(db, replacement_id):
    """Retire declared obsolete routes only after an actual replacement inventory.

    The old row remains visible and keeps all appearances and errors. A listing
    proof may coexist with a description budget; transport/parsing failures never
    allow retirement. No scope expansion or source identity rewriting occurs.
    """
    company_id = select(CompanySource.company_id).where(CompanySource.id == replacement_id).scalar_subquery()
    related = db.scalars(select(CompanySource).where(CompanySource.company_id == company_id)
                          .order_by(CompanySource.id).with_for_update().execution_options(populate_existing=True)).all()
    replacement = next((r for r in related if r.id == replacement_id),None)
    snapshot = (replacement.config or {}).get('board_health', {}) if replacement else {}
    if not replacement or not replacement.enabled or snapshot.get('inventory_complete') is not True:
        return 0
    if snapshot.get('status') not in ('complete', 'scoped_complete', 'partial'):
        return 0
    issue = snapshot.get('last_error') or ''
    if issue and any(x.strip() != 'detail_limit_reached' for x in issue.split(';') if x.strip()):
        return 0
    retired = []
    for original in related:
        if original.id == replacement.id or original.config.get('replacement_source_id') != replacement.id:
            continue
        if original.config.get('replacement_state') == 'superseded':
            continue
        original.config = {**original.config, 'replacement_state':'superseded',
            'retired_at':utcnow().isoformat(), 'retired_health':{
                'status':original.status, 'last_error':original.last_error,
                'was_enabled':original.enabled}}
        original.enabled = False
        original.status = 'superseded'
        retired.append(original.id)
    if retired:
        from .service import reconcile_availability
        db.flush()
        affected = db.scalars(select(Opportunity).where(Opportunity.id.in_(
            select(JobSource.opportunity_id).where(JobSource.company_source_id.in_(retired))))).all()
        for opportunity in affected:
            reconcile_availability(db,opportunity)
        db.add(Activity(kind='registry.superseded', title='Obsolete sources replaced after a live check',
            data={'replacement_source_id':replacement.id, 'retired_source_ids':retired,
                  'replacement_url':replacement.url}))
    db.commit()
    return len(retired)


def backfill_scoped_health(db):
    """Correct old scope labels only from the matching persisted board result.

    This does not perform a new check, make timestamps fresh, verify employer
    association, or authorize closures. The old fetch evidence remains intact.
    """
    from sqlalchemy import func
    from .source_health import _timestamp
    ranked = select(FetchRun.id.label('run_id'), FetchRun.company_source_id.label('source_id'),
        func.row_number().over(partition_by=FetchRun.company_source_id,
                              order_by=(FetchRun.created_at.desc(), FetchRun.id.desc())).label('position')
        ).where(FetchRun.coverage_scope != 'targeted').subquery()
    latest = {run.company_source_id: run for run in db.scalars(select(FetchRun).join(
        ranked, FetchRun.id == ranked.c.run_id).where(ranked.c.position == 1)).all()}
    corrections = []
    for row in db.scalars(select(CompanySource).where(CompanySource.status == 'partial')
                          .order_by(CompanySource.id).with_for_update().execution_options(populate_existing=True)).all():
        run = latest.get(row.id)
        if not run or row.config.get('board_health') or row.last_error or run.error:
            continue
        checked = _timestamp(row.config.get('board_checked_at')) or _timestamp(row.last_checked)
        evidence = run.data or {}
        if not run.finished_at or checked != aware(run.finished_at):
            continue
        if run.coverage_scope not in ('query', 'discovery') or evidence.get('requested_complete') is not True:
            continue
        collection=evidence.get('collection') or {}
        if evidence.get('issues') or evidence.get('invalid') or collection.get('errors'):
            continue
        if any(any(word in str(warning).lower() for word in ('bounded_discovery','truncat','page_limit','not_a_full_inventory'))
               for warning in collection.get('warnings', [])):
            continue
        row.status = 'scoped_complete'
        row.config = {**row.config, 'scope_label_correction':{'fetch_run_id':run.id,
            'corrected_at':utcnow().isoformat(), 'previous_status':'partial'},
            'board_health':{'status':'scoped_complete', 'last_error':None,
                'last_success':checked.isoformat(), 'consecutive_failures':0,
                'coverage_scope':run.coverage_scope, 'inventory_complete':True if run.coverage_scope=='query' else None,
                'description_complete':collection.get('description_complete'), 'full_inventory':False}}
        corrections.append({'source_id':row.id, 'fetch_run_id':run.id})
    if corrections:
        db.add(Activity(kind='registry.scope_labels', title='Prior successful target checks labelled accurately',
            data={'corrections':corrections, 'freshness_unchanged':True, 'new_network_checks':0}))
    db.commit()
    return len(corrections)
