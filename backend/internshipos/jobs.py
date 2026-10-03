"""Durable bounded work compatible with a local worker or free scheduled CI runs."""
import asyncio, logging, os, threading, time
from datetime import timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import String, JSON, DateTime, Integer, select, update
from sqlalchemy.orm import Mapped, mapped_column, joinedload
from .db import Base, SessionLocal, utcnow, aware
from .models import Company, CompanySource, Activity, Integration, Setting, Task, Notification

log=logging.getLogger(__name__)

class BackgroundJob(Base):
    __tablename__='background_jobs'
    id:Mapped[str]=mapped_column(String(36),primary_key=True,default=lambda:__import__('uuid').uuid4().hex)
    kind:Mapped[str]=mapped_column(String(80))
    payload:Mapped[dict]=mapped_column(JSON,default=dict)
    status:Mapped[str]=mapped_column(String(30),default='pending',index=True)
    attempts:Mapped[int]=mapped_column(Integer,default=0)
    created_at:Mapped[object]=mapped_column(DateTime(timezone=True),default=utcnow)
    started_at:Mapped[object]=mapped_column(DateTime(timezone=True),nullable=True)
    finished_at:Mapped[object]=mapped_column(DateTime(timezone=True),nullable=True)
    error:Mapped[str]=mapped_column(String(1000),nullable=True)

def enqueue(db,kind='collect',payload=None):
    existing=db.scalars(select(BackgroundJob).where(BackgroundJob.kind==kind,BackgroundJob.status.in_(['pending','running']))).first()
    if existing:return {'job_id':existing.id,'status':existing.status,'already_queued':True}
    job=BackgroundJob(kind=kind,payload=payload or {});db.add(job);db.commit();return {'job_id':job.id,'status':'queued'}

async def collect_boards(source_ids=None,limit=None,force=False):
    from .ingestion import collect_source
    from .service import ingest_batch
    batch_size=limit or int(os.getenv('COLLECTION_BATCH_SIZE','12'))
    with SessionLocal() as db:
        query=select(CompanySource).where(CompanySource.enabled==True)
        if source_ids:query=query.where(CompanySource.id.in_(source_ids))
        rows=db.scalars(query.options(joinedload(CompanySource.company))).all()
        def board_checked(row):
            stamp=(row.config or {}).get('board_checked_at')
            try:return aware(__import__('datetime').datetime.fromisoformat(stamp)) if stamp else aware(row.last_checked)
            except (ValueError,TypeError):return aware(row.last_checked)
        # Overdue age eventually outweighs source priority, avoiding starvation.
        rows.sort(key=lambda r: (-(72 if not board_checked(r) else (utcnow()-board_checked(r)).total_seconds()/3600)/(r.cadence_hours or 24)-1/max(1,r.priority),r.id))
        now=utcnow();sources=[]
        for row in rows:
            last=board_checked(row)
            retry_hours=min(72,2**min(row.consecutive_failures or 0,6)) if row.consecutive_failures else 0
            interval=max(row.cadence_hours or 24,retry_hours)
            if force or not last or now-last>=timedelta(hours=interval):
                source={c.name:getattr(row,c.name) for c in row.__table__.columns}
                company=row.company
                source.update(company_name=company.name if company else '',company_domain=company.domain if company else '')
                sources.append(source)
            if len(sources)>=batch_size:break
    semaphore=asyncio.Semaphore(int(os.getenv('COLLECTION_CONCURRENCY','3')))
    async def one(source):
        async with semaphore:
            try:result=await collect_source(source,
                max_details=int(os.getenv('COLLECTION_MAX_DETAILS','80')),
                max_pages=int(os.getenv('COLLECTION_MAX_PAGES','25')),
                timeout_seconds=int(os.getenv('COLLECTION_SOURCE_TIMEOUT','120')))
            except Exception as exc:
                from .ingestion import CollectionResult
                result=CollectionResult(jobs=[],complete=False,error=str(exc)[:600],coverage_scope='unknown')
            inventory_ids=None
            with SessionLocal() as db:
                if os.getenv('COLLECTION_TARGET_ONLY','false').lower()=='true':
                    from .models import JobSource
                    from .search_policy import retain_new_candidate
                    inventory_ids=[str(j.get('external_id')) for j in result.jobs]
                    existing=set(db.scalars(select(JobSource.external_id).where(JobSource.company_source_id==source['id'])).all())
                    # Existing appearances always update, preserving full-scan
                    # absence proofs even if a job's title/location changes.
                    result.jobs=[j for j in result.jobs if str(j.get('external_id')) in existing or retain_new_candidate(j)]
                outcome=await asyncio.to_thread(ingest_batch,db,source['id'],result.jobs,complete=result.complete,error=result.error,coverage_scope=result.coverage_scope,observed_count=result.observed_count,inventory_ids=inventory_ids)
                from .models import FetchRun
                fetched=db.get(FetchRun,outcome['run_id']);fetched.data={**fetched.data,'collection':result.metadata};db.commit()
                if result.metadata.get('next_detail_cursor') is not None:
                    row=db.get(CompanySource,source['id']);row.config={**row.config,'detail_cursor':result.metadata['next_detail_cursor']};db.commit()
                return outcome
    outcomes=await asyncio.gather(*(one(source) for source in sources),return_exceptions=True)
    return {'boards':len(sources),'results':[str(o) if isinstance(o,Exception) else o for o in outcomes]}

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
    try:
        with SessionLocal() as db:
            stale=utcnow()-timedelta(minutes=45)
            for row in db.scalars(select(BackgroundJob).where(BackgroundJob.status=='running',BackgroundJob.started_at<stale)).all():row.status='pending';row.error='Recovered an interrupted worker lease.'
            db.commit()
            job=db.scalars(select(BackgroundJob).where(BackgroundJob.status=='pending').order_by(BackgroundJob.created_at).limit(1)).first()
            if job:
                claimed=db.execute(update(BackgroundJob).where(BackgroundJob.id==job.id,BackgroundJob.status=='pending').values(status='running',started_at=utcnow(),attempts=BackgroundJob.attempts+1));db.commit()
                if not claimed.rowcount:return {'status':'claimed_elsewhere'}
                job_id,kind,payload=job.id,job.kind,job.payload
            else:job_id,kind,payload=None,'collect',{}
        try:
            if kind=='collect':result=asyncio.run(collect_boards(payload.get('source_ids'),payload.get('limit'),force=force or payload.get('force',False)))
            elif kind=='discover':
                with SessionLocal() as db:result=discover_registry(db,5)
            else:result={'status':'unsupported_job'}
            with SessionLocal() as db:
                if job_id:
                    job=db.get(BackgroundJob,job_id);job.status='completed';job.finished_at=utcnow();job.payload={**job.payload,'result':result}
                if job_id or result.get('boards') or kind=='discover':db.add(Activity(kind='collection',title='Collection completed',data=result))
                db.commit()
        except Exception as exc:
            log.exception('Background collection failed')
            with SessionLocal() as db:
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
            if not last or utcnow()-aware(__import__('datetime').datetime.fromisoformat(last))>=timedelta(hours=1):
                # Claim the maintenance window before network work so a restart
                # does not repeatedly re-fetch the same saved descriptions.
                db.merge(Setting(key='registry_maintenance',value={'at':utcnow().isoformat()}));db.commit()
                try:discover_registry(db,2);asyncio.run(refresh_saved_jobs())
                except Exception:db.rollback();log.exception('Registry/detail maintenance needs attention')
            db.merge(Setting(key='worker_heartbeat',value={'at':utcnow().isoformat(),'result':result}));db.commit()
        return result
    finally:_tick_lock.release()

def worker_loop(stop):
    # Tick each minute to service durable requests; source due dates throttle network work.
    while not stop.wait(10):
        run_tick();stop.wait(50)

if __name__=='__main__':
    from .db import init_db
    from .seed import seed_database
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['tick','worker']);parser.add_argument('--force',action='store_true');args=parser.parse_args()
    init_db()
    with SessionLocal() as db:seed_database(db)
    if args.command=='tick':print(run_tick(args.force))
    else:
        try:worker_loop(threading.Event())
        except KeyboardInterrupt:pass
