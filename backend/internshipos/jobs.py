"""Durable bounded work compatible with a local worker or free scheduled CI runs."""
import asyncio, copy, logging, os, threading, time
from uuid import uuid4
from datetime import timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import select, update
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import DBAPIError, IntegrityError
from .db import SessionLocal, utcnow, aware
from .worker_models import BackgroundJob, WorkerLease
from .models import Company, CompanySource, Activity, Integration, Setting, Task, Notification

log=logging.getLogger(__name__)


def _aborted_postgres_transaction(db, exc):
    """Only server-confirmed transaction aborts are safe to replay.

    Transport/connection failures may have an ambiguous commit outcome and must
    remain failures. Do not match exception messages or retry other databases.
    """
    if not isinstance(exc, DBAPIError) or exc.connection_invalidated:
        return False
    original = exc.orig
    code = getattr(original, 'sqlstate', None) or getattr(original, 'pgcode', None)
    return code in {'40P01', '40001'} and db.get_bind().dialect.name == 'postgresql'


def _persist_transaction(db, operation, *, source_id, stage, max_attempts=3):
    """Replay a rolled-back atomic operation, with at most three attempts."""
    max_attempts = max(1, min(3, max_attempts))
    for attempt in range(max_attempts):
        try:
            return operation(), attempt
        except Exception as exc:
            retryable = _aborted_postgres_transaction(db, exc)
            db.rollback()  # Ends the failed transaction; the next call starts fresh.
            if not retryable or attempt + 1 >= max_attempts:
                raise
            code = getattr(exc.orig, 'sqlstate', None) or getattr(exc.orig, 'pgcode', None)
            log.warning('Retrying %s for source %s after PostgreSQL %s (%s/%s)',
                        stage, source_id, code, attempt + 1, max_attempts)
            time.sleep(0.1 * (attempt + 1))

def collection_limits():
    def number(key,default,low,high):
        try:return max(low,min(high,int(os.getenv(key,str(default)))))
        except (ValueError,TypeError):return default
    return {'source_limit':number('COLLECTION_BATCH_SIZE',12,1,2000),
            'concurrency':number('COLLECTION_CONCURRENCY',3,1,12),
            'source_timeout_seconds':number('COLLECTION_SOURCE_TIMEOUT',120,5,600),
            'run_budget_seconds':number('COLLECTION_RUN_BUDGET_SECONDS',1560,30,1800),
            'persistence_reserve_seconds':30}


def _claim_worker_lease(db,now=None):
    now=aware(now or utcnow());token=uuid4().hex
    # The lease outlives collection plus bounded maintenance. A replacement
    # worker can recover only after expiry, never on a scheduled trigger alone.
    values={'token':token,'started_at':now,'expires_at':now+timedelta(minutes=40)}
    row=db.get(WorkerLease,'collection')
    if row is None:
        try:
            db.add(WorkerLease(name='collection',**values));db.commit();return token
        except IntegrityError:
            db.rollback()  # Another process created the row first.
    claimed=db.execute(update(WorkerLease).where(WorkerLease.name=='collection',
        WorkerLease.expires_at<=now).values(**values).execution_options(synchronize_session=False));db.commit()
    return token if claimed.rowcount else None


def _lease_owned(db,token,now=None):
    if not token:return True
    return bool(db.scalar(select(WorkerLease.name).where(WorkerLease.name=='collection',
        WorkerLease.token==token,WorkerLease.expires_at>aware(now or utcnow()))))


def _release_worker_lease(db,token):
    db.execute(update(WorkerLease).where(WorkerLease.name=='collection',WorkerLease.token==token)
        .values(expires_at=utcnow()).execution_options(synchronize_session=False));db.commit()


def _ordered_due_sources(rows,now,force=False):
    """Three preferred slots and one oldest-due slot; owner priority is unchanged.

    Preferences are bounded. Oldest-due service reserves a quarter of capacity,
    so a recurring stream of high-priority boards cannot starve the long tail.
    Failure backoff is enforced before either lane is built.
    """
    from .source_health import timing,board_observation
    eligible=[]
    for row in rows:
        if row.enabled is False:continue
        state=timing(row,now)
        if not force and not state['due']:continue
        due_at=state['next_due_at'] or aware(getattr(row,'created_at',None)) or now-timedelta(hours=24)
        wait=max(0,(now-due_at).total_seconds()/3600)
        observation=board_observation(row)
        working=observation['status'] in ('complete','scoped_complete','partial') and not observation['consecutive_failures']
        config=row.config or {}
        scope=' '.join(str(config.get(k,'')) for k in ('country_name','location','search_text','params')).lower()
        relevant=any(term in scope for term in ('india','chennai','bengaluru','bangalore',"'countries': 'in'"))
        bonus=(2 if working else 0)+(0.5 if row.verified else 0)+(0.5 if relevant else 0)+1/max(1,row.priority or 2)
        eligible.append((row,due_at,wait/state['effective_interval_hours']+bonus))
    preferred=sorted(eligible,key=lambda item:(-item[2],item[1],item[0].id))
    oldest=sorted(eligible,key=lambda item:(item[1],item[0].id))
    result=[];seen=set();pi=oi=0
    while len(result)<len(eligible):
        lane=oldest if len(result)%4==3 else preferred
        index=oi if lane is oldest else pi
        while index<len(lane) and lane[index][0].id in seen:index+=1
        if index>=len(lane):break
        row=lane[index][0];result.append(row);seen.add(row.id)
        if lane is oldest:oi=index+1
        else:pi=index+1
    return result

def enqueue(db,kind='collect',payload=None):
    query=select(BackgroundJob).where(BackgroundJob.kind==kind,BackgroundJob.status.in_(['pending','running']))
    if kind=='refresh_opportunity':
        query=query.where(BackgroundJob.payload['opportunity_id'].as_string()==str((payload or {}).get('opportunity_id') or ''))
    existing=db.scalars(query).first()
    if existing:return {'job_id':existing.id,'status':existing.status,'already_queued':True}
    job=BackgroundJob(kind=kind,payload=payload or {});db.add(job);db.commit();return {'job_id':job.id,'status':'queued'}

def _collection_waves(sources,concurrency):
    """Give paced public searches room within each source's time allowance."""
    pending=list(sources)
    while pending:
        wave=[];remaining=[];linkedin=0
        for source in pending:
            paced=source.get('provider')=='linkedin' or (source.get('provider')=='jobspy' and (source.get('config') or {}).get('site')=='linkedin')
            if len(wave)<concurrency and (not paced or linkedin<2):
                wave.append(source);linkedin+=int(paced)
            else:remaining.append(source)
        yield wave
        pending=remaining


async def collect_boards(source_ids=None,limit=None,force=False,lease_token=None):
    from .ingestion import collect_source
    from .service import ingest_batch
    limits=collection_limits()
    batch_size=max(1,min(2000,int(limit or limits['source_limit'])))
    started=time.monotonic();deadline=started+limits['run_budget_seconds']
    with SessionLocal() as db:
        query=select(CompanySource).where(CompanySource.enabled==True)
        if source_ids is not None:query=query.where(CompanySource.id.in_(source_ids))
        rows=db.scalars(query.options(joinedload(CompanySource.company))).all()
        rows=_ordered_due_sources(rows,utcnow(),force)
        target_only=os.getenv('COLLECTION_TARGET_ONLY','false').lower()=='true'
        retained={}
        if target_only and rows:
            from .models import JobSource
            for ident,external_id in db.execute(select(JobSource.company_source_id,JobSource.external_id)
                    .where(JobSource.company_source_id.in_([row.id for row in rows[:batch_size]]))):
                retained.setdefault(ident,[]).append(external_id)
        sources=[]
        for row in rows[:batch_size]:
            source={c.name:getattr(row,c.name) for c in row.__table__.columns}
            company=row.company
            source.update(company_name=company.name if company else '',company_domain=company.domain if company else '')
            if target_only:
                source['config']={**source.get('config',{}),'detail_target_only':True,
                    'retained_external_ids':retained.get(row.id,[])}
            sources.append(source)
        remaining_ids=[row.id for row in rows[batch_size:]]
    semaphore=asyncio.Semaphore(limits['concurrency'])
    async def one(source):
        async with semaphore:
            try:result=await collect_source(source,
                max_details=int(os.getenv('COLLECTION_MAX_DETAILS','80')),
                max_pages=int(os.getenv('COLLECTION_MAX_PAGES','25')),
                timeout_seconds=limits['source_timeout_seconds'])
            except Exception as exc:
                from .ingestion import CollectionResult
                result=CollectionResult(jobs=[],complete=False,error=str(exc)[:600],coverage_scope='unknown')
            # Keep the collected observation immutable across transaction aborts.
            # Re-read existing appearances in each fresh transaction before the
            # storage filter, so another collector cannot make that filter stale.
            collected_jobs=copy.deepcopy(result.jobs)
            collected_metadata=copy.deepcopy(result.metadata)
            target_only=os.getenv('COLLECTION_TARGET_ONLY','false').lower()=='true'
            with SessionLocal() as db:
                def ingest():
                    observations=copy.deepcopy(collected_jobs)
                    inventory_ids=None
                    if target_only:
                        from .models import JobSource
                        from .search_policy import retain_new_candidate
                        inventory_ids=[str(j.get('external_id')) for j in observations]
                        existing=set(db.scalars(select(JobSource.external_id).where(JobSource.company_source_id==source['id'])).all())
                        observations=[j for j in observations if str(j.get('external_id')) in existing or retain_new_candidate(j)]
                    return ingest_batch(db,source['id'],observations,complete=result.complete,error=result.error,
                        coverage_scope=result.coverage_scope,observed_count=result.observed_count,inventory_ids=inventory_ids,
                        inventory_complete=collected_metadata.get('inventory_complete'),
                        collection_metadata=copy.deepcopy(collected_metadata))
                outcome,ingest_retries=await asyncio.to_thread(_persist_transaction,db,ingest,
                    source_id=source['id'],stage='ingest')
                from .source_repairs import retire_replaced_sources
                # Ingestion commits before retirement. Retrying retirement must
                # never replay a successfully committed observation batch.
                _,retire_retries=await asyncio.to_thread(_persist_transaction,db,
                    lambda:retire_replaced_sources(db,source['id']),source_id=source['id'],stage='retire')
                outcome['persistence_retries']={'ingest':ingest_retries,'retire':retire_retries}
                return outcome
    results=[];started_count=0;budget_exhausted=False;lease_lost=False
    # Waves avoid a queue of semaphore waiters starting after the run budget.
    # Observations in a started wave finish persistence before we stop.
    waves=list(_collection_waves(sources,limits['concurrency']))
    for offset,wave in enumerate(waves):
        if deadline-time.monotonic()<limits['source_timeout_seconds']+limits['persistence_reserve_seconds']:
            budget_exhausted=True;remaining_ids=[s['id'] for pending in waves[offset:] for s in pending]+remaining_ids;break
        if lease_token:
            with SessionLocal() as db:owned=_lease_owned(db,lease_token)
            if not owned:
                lease_lost=True;remaining_ids=[s['id'] for pending in waves[offset:] for s in pending]+remaining_ids;break
        outcomes=await asyncio.gather(*(one(source) for source in wave),return_exceptions=True)
        started_count+=len(wave)
        results.extend({'source_id':wave[i]['id'],'status':'worker_error','error':str(outcome)[:600]}
            if isinstance(outcome,Exception) else outcome for i,outcome in enumerate(outcomes))
    from collections import Counter
    return {'boards':started_count,'selected_boards':len(sources),'eligible_boards':len(rows),
            'deferred_boards':len(remaining_ids),'remaining_source_ids':remaining_ids,
            'run_budget_exhausted':budget_exhausted,'lease_lost':lease_lost,
            'elapsed_seconds':round(time.monotonic()-started,2),'limits':limits,
            'results':results,'statuses':dict(Counter(o.get('status','unknown') for o in results)),
            'worker_errors':sum(o.get('status')=='worker_error' for o in results)+(1 if lease_lost else 0)}

def morning_digest(db):
    from .service import dashboard
    tz=db.get(Setting,'timezone');local=utcnow().astimezone(ZoneInfo(str(tz.value) if tz else 'Asia/Kolkata'))
    data=dashboard(db);today=local.date().isoformat();key='digest:'+today
    if db.get(Setting,key):return {'status':'already_created'}
    stats=data['stats'];opportunities=data['top_opportunities'][:5]
    text=f"{stats.get('new_opportunities',0)} new opportunities; {len(data.get('deadlines',[]))} upcoming tasks."
    notification=Notification(title='Your internship briefing',body=text,kind='digest',data={'date':today,'opportunity_ids':[o['id'] for o in opportunities]});db.add(notification);db.add(Setting(key=key,value={'created_at':utcnow().isoformat()}));db.commit();return {'status':'created','briefing':text}

async def refresh_saved_jobs(limit=8):
    from .service import saved_refresh_candidates,ingest_batch
    from .ingestion import collect_source
    with SessionLocal() as db:candidates=saved_refresh_candidates(db,limit=limit)
    results=[]
    for source in candidates:
        result=await collect_source(source,max_pages=2,max_jobs=20,max_details=8,max_requests=15,timeout_seconds=45)
        with SessionLocal() as db:
            results.append(ingest_batch(db,source['id'],result.jobs,complete=False,error=result.error,coverage_scope='targeted',observed_count=result.observed_count))
    return {'sources':len(candidates),'results':results}


async def refresh_opportunity(opportunity_id):
    """Server-resolved exact appearances; a targeted read cannot close a vacancy."""
    from .models import Opportunity,JobSource
    from .domain import canonicalize_url
    from .service import ingest_batch
    from .ingestion import collect_source
    from .source_health import timing
    with SessionLocal() as db:
        op=db.get(Opportunity,str(opportunity_id))
        if not op:return {'opportunity_id':str(opportunity_id),'sources':0,'worker_errors':0,'status':'needs_review','reason':'Opportunity no longer exists.'}
        if (op.data or {}).get('identity_review'):
            return {'opportunity_id':op.id,'sources':0,'worker_errors':0,'status':'needs_review','reason':'Historical identity must be reviewed before a live recheck.'}
        appearances=db.scalars(select(JobSource).join(CompanySource).where(JobSource.opportunity_id==op.id,
            CompanySource.enabled.is_(True),CompanySource.verified.is_(True),CompanySource.company_id==op.company_id)
            .options(joinedload(JobSource.company_source).joinedload(CompanySource.company))
            .order_by(JobSource.last_detail_checked.asc().nullsfirst(),JobSource.id)).all()
        candidates=[]
        for appearance in appearances:
            if appearance.status == 'historical_alias':continue
            source=appearance.company_source
            if timing(source)['backoff']:continue
            url=canonicalize_url(appearance.url or op.canonical_url)
            if not url or not appearance.external_id:continue
            target={'external_id':appearance.external_id,'requisition_id':appearance.requisition_id,
                'canonical_url':url,'apply_url':op.apply_url,'opportunity_id':op.id,'title':op.title,
                'company_name':op.company.name,'company_domain':op.company.domain,'company_aliases':op.company.aliases}
            data={column.name:getattr(source,column.name) for column in source.__table__.columns}
            data.update(company_name=source.company.name,company_domain=source.company.domain,
                config={**(source.config or {}),'refresh_external_ids':[appearance.external_id],'refresh_jobs':[target]})
            candidates.append(data)
            if len(candidates)>=3:break
    if not candidates:
        return {'opportunity_id':str(opportunity_id),'sources':0,'worker_errors':0,'status':'needs_review',
                'reason':'No enabled verified source for this employer is available outside its retry window.'}
    outcomes=[]
    for source in candidates:
        try:
            result=await collect_source(source,max_pages=2,max_jobs=20,max_details=2,max_requests=10,timeout_seconds=45)
            expected=str(source['config']['refresh_external_ids'][0])
            # Target adapters must return only the proven appearance. Reject an
            # unexpected record before ingestion rather than trusting its title.
            observations=[row for row in result.jobs if str(row.get('external_id'))==expected]
            unexpected=len(observations)!=len(result.jobs)
            error='targeted_refresh_returned_unrequested_identity' if unexpected else result.error
            with SessionLocal() as db:
                outcome,retries=await asyncio.to_thread(_persist_transaction,db,
                    lambda:ingest_batch(db,source['id'],[] if unexpected else copy.deepcopy(observations),
                        complete=False,error=error,coverage_scope='targeted',observed_count=len(observations),
                        collection_metadata=copy.deepcopy(result.metadata)),source_id=source['id'],stage='targeted_refresh')
            outcome['persistence_retries']={'ingest':retries};outcomes.append(outcome)
        except Exception as exc:
            outcomes.append({'source_id':source['id'],'status':'worker_error','error':str(exc)[:600]})
    failed=sum(row.get('status')=='worker_error' for row in outcomes)
    return {'opportunity_id':str(opportunity_id),'sources':len(candidates),'results':outcomes,'worker_errors':failed,
            'status':'needs_review' if any(row.get('status') in ('error','quarantined','worker_error') for row in outcomes) else 'checked'}

def discover_registry(db,limit=3):
    from .ingestion import discover_company
    now=utcnow();eligible=[]
    for company in db.scalars(select(Company)).all():
        if company.metadata_json.get('source_holder'):continue
        prior=company.metadata_json.get('discovery',{})
        checked=prior.get('checked_at')
        if checked and now-aware(__import__('datetime').datetime.fromisoformat(checked))<timedelta(hours=prior.get('retry_after_hours',168)):continue
        eligible.append((checked or '',company))
    eligible.sort(key=lambda x:x[0]);results=[]
    for _,company in eligible[:limit]:
        result=asyncio.run(discover_company(company.name,company.domain,company.careers_url,trusted_domain=company.verified));results.append(result)
        company.metadata_json={**company.metadata_json,'discovery':result};company.updated_at=now
        for candidate in result.get('sources',[]):
            existing=db.scalar(select(CompanySource).where(CompanySource.company_id==company.id,CompanySource.url==candidate.get('url')))
            verified=bool(company.verified and candidate.get('verified') and candidate.get('config',{}).get('association_evidence'))
            if existing:
                existing.config={**existing.config,**candidate.get('config',{})};existing.verified=verified or existing.verified
            else:db.add(CompanySource(company_id=company.id,provider=candidate.get('provider','html'),url=candidate['url'],board=candidate.get('board'),config=candidate.get('config',{}),verified=verified,enabled=True,priority=3,cadence_hours=24))
    db.commit();return {'companies':len(results),'source_associations':sum(len(r.get('sources',[])) for r in results)}

def scheduled_notifications(db):
    enabled=db.get(Setting,'notifications_enabled')
    if enabled and not enabled.value:return
    now=utcnow();tz=db.get(Setting,'timezone');local=now.astimezone(ZoneInfo(str(tz.value) if tz else 'Asia/Kolkata'))
    if local.hour>=7:morning_digest(db)
    from .service import dashboard
    for op in dashboard(db)['top_opportunities']:
        if (op.get('fit_score') or 0)<80 or (op.get('worth_score') or 0)<70 or op.get('application_id'):continue
        key='strong_opportunity:'+op['id']
        if not db.get(Setting,key):
            db.add(Setting(key=key,value={'at':now.isoformat()}));db.add(Notification(title='A strong opportunity',body=op['company']['name']+' · '+op['title'],kind='opportunity',data={'opportunity_id':op['id']}))
    for task in db.scalars(select(Task).where(Task.completed==False,Task.due_at!=None)).all():
        if not now<=aware(task.due_at)<=now+timedelta(hours=24):continue
        key='deadline_alert:'+task.id+':'+aware(task.due_at).date().isoformat()
        if not db.get(Setting,key):
            db.add(Setting(key=key,value={'at':now.isoformat()}));db.add(Notification(title='Upcoming deadline',body=task.title,kind='deadline',data={'task_id':task.id,'due_at':aware(task.due_at).isoformat()}))
    db.commit()

_tick_lock=threading.Lock()
def run_tick(force=False):
    if not _tick_lock.acquire(blocking=False):return {'status':'already_running'}
    lease_token=None
    try:
        with SessionLocal() as db:
            lease_token=_claim_worker_lease(db)
            if not lease_token:return {'status':'already_running','detail':'Another worker owns the collection lease.'}
            stale=utcnow()-timedelta(minutes=40)
            for row in db.scalars(select(BackgroundJob).where(BackgroundJob.status=='running',BackgroundJob.started_at<stale)).all():row.status='pending';row.error='Recovered an interrupted worker lease.'
            db.commit()
            job=db.scalars(select(BackgroundJob).where(BackgroundJob.status=='pending').order_by(BackgroundJob.created_at).limit(1)).first()
            if job:
                claimed=db.execute(update(BackgroundJob).where(BackgroundJob.id==job.id,BackgroundJob.status=='pending').values(status='running',started_at=utcnow(),attempts=BackgroundJob.attempts+1));db.commit()
                if not claimed.rowcount:return {'status':'claimed_elsewhere'}
                job_id,kind,payload=job.id,job.kind,job.payload
            else:job_id,kind,payload=None,'collect',{}
        try:
            if kind=='collect':result=asyncio.run(collect_boards(payload.get('source_ids'),payload.get('limit'),force=force or payload.get('force',False),lease_token=lease_token))
            elif kind=='refresh_opportunity':result=asyncio.run(refresh_opportunity(payload.get('opportunity_id')))
            elif kind=='discover':
                with SessionLocal() as db:result=discover_registry(db,5)
            else:result={'status':'unsupported_job'}
            with SessionLocal() as db:
                if not _lease_owned(db,lease_token):
                    return {'status':'failed','worker_errors':1,'detail':'Worker lease expired; replacement worker owns completion.'}
                if job_id:
                    job=db.get(BackgroundJob,job_id)
                    continuation=kind=='collect' and result.get('remaining_source_ids') and not result.get('worker_errors')
                    job.status='failed' if result.get('worker_errors') else 'pending' if continuation else 'completed'
                    job.finished_at=None if continuation else utcnow()
                    job.payload={**job.payload,'result':result}
                    if continuation:
                        # Preserve the exact request and force setting, replacing
                        # only its unfinished source list. Collected sources are
                        # never replayed merely because a run hit its bound.
                        job.payload={**job.payload,'source_ids':result['remaining_source_ids'],'force':force or payload.get('force',False)}
                        job.error='Unstarted boards remain queued for the next bounded run.'
                    elif not result.get('worker_errors'):job.error=None
                    if result.get('worker_errors'):job.error='One or more source results could not be persisted; inspect collection evidence.'
                if job_id or result.get('boards') or kind=='discover':db.add(Activity(kind='collection',title='Collection needs attention' if result.get('worker_errors') else 'Collection checked a batch; more sources remain' if result.get('remaining_source_ids') else 'Collection completed',data=result))
                if kind=='collect':db.merge(Setting(key='collection_last_run',value={'at':utcnow().isoformat(),'result':result}))
                db.commit()
        except Exception as exc:
            log.exception('Background collection failed')
            with SessionLocal() as db:
                if _lease_owned(db,lease_token):
                    if job_id:job=db.get(BackgroundJob,job_id);job.status='failed';job.finished_at=utcnow();job.error=str(exc)[:1000]
                    db.add(Activity(kind='system_error',title='Collection needs attention',body=str(exc)[:500]));db.commit()
            result={'status':'failed','detail':str(exc)[:300]}
        with SessionLocal() as db:
            row=db.scalars(select(Integration).where(Integration.provider=='google')).first()
            if row and row.credentials_encrypted:
                last=row.data.get('last_polled_at')
                cadence=db.get(Setting,'gmail_poll_minutes')
                interval=float(cadence.value) if cadence else 45
                if not last or utcnow()-aware(__import__('datetime').datetime.fromisoformat(last))>=timedelta(minutes=interval):
                    try:
                        from .integrations import poll_gmail,calendar_sync
                        poll_gmail(db);calendar_sync(db)
                    except Exception as exc:
                        db.rollback();key='google_failure:'+utcnow().date().isoformat()
                        if not db.get(Setting,key):db.add(Setting(key=key,value={'at':utcnow().isoformat()}));db.add(Notification(title='Google connection needs attention',body=str(exc)[:250],kind='integration'));db.commit()
            scheduled_notifications(db)
            maintenance=db.get(Setting,'registry_maintenance')
            last=maintenance.value.get('at') if maintenance else None
            # Reserve time for heartbeat and lease release. This bounded job is
            # already behind if collection used its window; defer optional
            # discovery/detail maintenance rather than losing the entire run.
            spare_seconds=collection_limits()['run_budget_seconds']-result.get('elapsed_seconds',0)
            if spare_seconds>=600 and (not last or utcnow()-aware(__import__('datetime').datetime.fromisoformat(last))>=timedelta(hours=1)):
                # Claim the maintenance window before network work so a restart
                # does not repeatedly re-fetch the same saved descriptions.
                db.merge(Setting(key='registry_maintenance',value={'at':utcnow().isoformat()}));db.commit()
                try:discover_registry(db,2);asyncio.run(refresh_saved_jobs())
                except Exception:db.rollback();log.exception('Registry/detail maintenance needs attention')
            if _lease_owned(db,lease_token):
                db.merge(Setting(key='worker_heartbeat',value={'at':utcnow().isoformat(),'kind':kind,'result':result}));db.commit()
        return result
    finally:
        try:
            if lease_token:
                with SessionLocal() as db:_release_worker_lease(db,lease_token)
        finally:_tick_lock.release()

def worker_loop(stop):
    # Tick each minute to service durable requests; source due dates throttle network work.
    while not stop.wait(10):
        run_tick();stop.wait(50)

def main(argv=None):
    from .db import init_db
    from .seed import seed_database
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['tick','worker']);parser.add_argument('--force',action='store_true');args=parser.parse_args(argv)
    init_db()
    with SessionLocal() as db:seed_database(db)
    if args.command=='tick':
        result=run_tick(args.force);print(result)
        return 1 if result.get('worker_errors') or result.get('status')=='failed' else 0
    else:
        try:worker_loop(threading.Event())
        except KeyboardInterrupt:pass
    return 0


if __name__=='__main__':
    raise SystemExit(main())
