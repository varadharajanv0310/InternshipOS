"""Run bounds keep observations; leases exclude other processes; aging is fair."""
import asyncio
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine,select
from sqlalchemy.orm import sessionmaker

from internshipos import jobs,service,source_repairs
from internshipos.db import Base
from internshipos.ingestion import CollectionResult
from internshipos.models import Company,CompanySource,Setting

NOW=datetime(2026,10,8,8,tzinfo=timezone.utc)


def test_clean_standalone_bootstrap_registers_queue_and_worker_lease(tmp_path):
    backend=Path(__file__).resolve().parents[1]
    environment={**os.environ,'PYTHONPATH':str(backend),
        'DATABASE_URL':'sqlite:///'+(tmp_path/'clean'/'bootstrap.db').as_posix(),
        'INTERNSHIPOS_DATA_DIR':str(tmp_path/'clean')}
    script='\n'.join([
        'import sys',
        'from internshipos.db import init_db, engine',
        "assert 'internshipos.jobs' not in sys.modules",
        'from sqlalchemy import inspect',
        'init_db()',
        'tables = set(inspect(engine).get_table_names())',
        "assert {'background_jobs', 'collection_worker_leases'} <= tables, tables",
        'init_db()',
        'engine.dispose()',
    ])
    result=subprocess.run([sys.executable,'-c',script],cwd=tmp_path,env=environment,
        capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr


def test_scheduled_module_entry_registers_models_once_and_finishes_empty_tick(tmp_path):
    backend=Path(__file__).resolve().parents[1]
    environment={**os.environ,'PYTHONPATH':str(backend),'SCHEDULER_ENABLED':'false',
        'DATABASE_URL':'sqlite:///'+(tmp_path/'module-entry.db').as_posix(),
        'INTERNSHIPOS_DATA_DIR':str(tmp_path/'runtime')}
    script='\n'.join([
        'import runpy, sys',
        'from internshipos import seed',
        # The actual CLI path runs against an empty fixture, never live sources.
        'seed.seed_database = lambda db: None',
        "sys.argv = ['internshipos.jobs', 'tick']",
        "runpy.run_module('internshipos.jobs', run_name='__main__')",
    ])
    result=subprocess.run([sys.executable,'-c',script],cwd=tmp_path,env=environment,
        capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    assert "'worker_errors': 0" in result.stdout,result.stdout
    assert "'boards': 0" in result.stdout,result.stdout


def board(ident,**changes):
    data=dict(id=ident,config={},last_checked=NOW-timedelta(hours=2),last_success=None,
        last_error=None,consecutive_failures=0,cadence_hours=1,status='complete',
        enabled=True,verified=True,priority=1,created_at=NOW-timedelta(days=10))
    data.update(changes);return SimpleNamespace(**data)


def test_oldest_due_lane_services_long_tail_despite_recurring_preferred_boards():
    preferred=[board('preferred-'+str(i)) for i in range(20)]
    tail=[board('tail-'+str(i),status='error',verified=False,priority=3,cadence_hours=168,
        last_checked=NOW-timedelta(hours=190+i)) for i in range(12)]
    seen=set()
    for cycle in range(4):
        now=NOW+timedelta(hours=cycle)
        selected=jobs._ordered_due_sources(preferred+tail,now)[:12]
        assert any(row.id.startswith('preferred-') for row in selected)
        for row in selected:
            if row.id.startswith('tail-'):seen.add(row.id)
            row.last_checked=now
    assert seen=={row.id for row in tail}


def test_due_plan_excludes_paused_and_backoff_without_mutating_preferences():
    rows=[board('paused',enabled=False),board('backoff',status='error',consecutive_failures=6),
          board('india',config={'country_name':'India'}),board('normal')]
    assert [row.id for row in jobs._ordered_due_sources(rows,NOW)]==['india','normal']
    assert rows[0].enabled is False and rows[1].cadence_hours==1 and rows[1].priority==1
    assert 'paused' not in [row.id for row in jobs._ordered_due_sources(rows,NOW,force=True)]


def test_paced_searches_share_waves_without_starving_unrelated_feeds():
    sources=[{'id':'li'+str(i),'provider':'linkedin'} for i in range(6)]+[
        {'id':'other'+str(i),'provider':'greenhouse'} for i in range(4)]
    waves=list(jobs._collection_waves(sources,6))
    assert len(waves[0])==6  # Spare slots service unrelated sources immediately.
    assert all(sum(s['provider']=='linkedin' for s in wave)<=2 for wave in waves)
    assert {s['id'] for wave in waves for s in wave}=={s['id'] for s in sources}
    assert sum(map(len,waves))==len(sources)


@pytest.fixture
def factory(tmp_path,monkeypatch):
    engine=create_engine('sqlite:///'+str(tmp_path/'scheduler.db'),connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine);factory=sessionmaker(bind=engine,expire_on_commit=False)
    monkeypatch.setattr(jobs,'SessionLocal',factory)
    monkeypatch.setenv('COLLECTION_TARGET_ONLY','false')
    monkeypatch.setenv('COLLECTION_CONCURRENCY','2')
    monkeypatch.setenv('COLLECTION_SOURCE_TIMEOUT','10')
    monkeypatch.setenv('COLLECTION_RUN_BUDGET_SECONDS','60')
    yield factory
    engine.dispose()


def seed_sources(factory,count=5):
    with factory() as db:
        company=Company(name='Fixture');db.add(company);db.flush()
        sources=[CompanySource(company_id=company.id,provider='fixture',url='https://example.test/'+str(i),enabled=True) for i in range(count)]
        db.add_all(sources);db.commit();return [source.id for source in sources]


def stub_persistence(monkeypatch):
    def ingest(db,ident,batch,**kwargs):
        db.add(Setting(key='observed-'+ident,value=True));db.commit()
        return {'source_id':ident,'status':'complete'}
    monkeypatch.setattr(service,'ingest_batch',ingest)
    monkeypatch.setattr(source_repairs,'retire_replaced_sources',lambda db,ident:0)


def test_worker_stops_new_waves_but_keeps_started_observations(factory,monkeypatch):
    ids=seed_sources(factory);stub_persistence(monkeypatch);clock=[0];calls=[]
    monkeypatch.setattr(jobs,'time',SimpleNamespace(monotonic=lambda:clock[0],sleep=lambda delay:None))
    async def collect(source,**kwargs):
        calls.append(source['id']);clock[0]+=9
        return CollectionResult(jobs=[],complete=True)
    monkeypatch.setattr('internshipos.ingestion.collect_source',collect)
    result=asyncio.run(jobs.collect_boards(ids,limit=5,force=True))
    assert result['boards']==4 and result['selected_boards']==5 and result['deferred_boards']==1
    assert result['run_budget_exhausted'] and result['worker_errors']==0
    assert set(calls).isdisjoint(result['remaining_source_ids'])
    with factory() as db:
        assert len(db.scalars(select(Setting)).all())==4
        untouched=db.get(CompanySource,result['remaining_source_ids'][0])
        assert untouched.last_checked is None


def test_explicit_empty_list_never_expands_to_registry(factory,monkeypatch):
    seed_sources(factory)
    async def collect(*args,**kwargs):pytest.fail('An empty explicit list must make no network requests')
    monkeypatch.setattr('internshipos.ingestion.collect_source',collect)
    assert asyncio.run(jobs.collect_boards([],force=True))['boards']==0


def test_lease_claim_excludes_other_session_and_expired_owner_cannot_release(factory,monkeypatch):
    with factory() as first:
        token=jobs._claim_worker_lease(first,NOW)
        assert token
    with factory() as second:
        assert jobs._claim_worker_lease(second,NOW+timedelta(minutes=39)) is None
        replacement=jobs._claim_worker_lease(second,NOW+timedelta(minutes=41))
        assert replacement and replacement!=token
        assert not jobs._lease_owned(second,token,NOW+timedelta(minutes=41))
        monkeypatch.setattr(jobs,'utcnow',lambda:NOW+timedelta(minutes=41))
        jobs._release_worker_lease(second,token)
        assert jobs._lease_owned(second,replacement,NOW+timedelta(minutes=41))


def test_concurrent_first_claim_has_exactly_one_owner(factory):
    barrier=threading.Barrier(2)
    def claim():
        with factory() as db:
            barrier.wait(timeout=5)
            return jobs._claim_worker_lease(db,NOW)
    with ThreadPoolExecutor(max_workers=2) as executor:
        tokens=list(executor.map(lambda _:claim(),range(2)))
    assert sum(bool(token) for token in tokens)==1


def test_tick_preserves_exact_unstarted_queue_and_does_not_claim_success(factory,monkeypatch):
    ids=seed_sources(factory,3)
    with factory() as db:
        queued=jobs.enqueue(db,payload={'source_ids':ids[:2],'force':True,'limit':2})
        db.add(Setting(key='registry_maintenance',value={'at':NOW.isoformat()}));db.commit()
    monkeypatch.setattr(jobs,'utcnow',lambda:NOW)
    monkeypatch.setattr(jobs,'scheduled_notifications',lambda db:None)
    seen=[]
    async def collect(source_ids,limit,**kwargs):
        seen.append((source_ids,limit,kwargs['force']))
        return {'boards':1,'worker_errors':0,'remaining_source_ids':[ids[1]],
            'run_budget_exhausted':True,'deferred_boards':1,'elapsed_seconds':1560}
    monkeypatch.setattr(jobs,'collect_boards',collect)
    result=jobs.run_tick()
    assert result['boards']==1 and seen==[(ids[:2],2,True)]
    with factory() as db:
        job=db.get(jobs.BackgroundJob,queued['job_id'])
        assert job.status=='pending' and job.finished_at is None
        assert job.payload['source_ids']==[ids[1]] and job.payload['force'] is True
        assert job.payload['result']['run_budget_exhausted'] is True
        assert not jobs._lease_owned(db,db.get(jobs.WorkerLease,'collection').token,NOW+timedelta(seconds=1))


def test_lost_lease_never_starts_source_or_updates_board_clock(factory,monkeypatch):
    ids=seed_sources(factory,1)
    async def collect(*args,**kwargs):pytest.fail('Lost lease must stop before network requests')
    monkeypatch.setattr('internshipos.ingestion.collect_source',collect)
    result=asyncio.run(jobs.collect_boards(ids,force=True,lease_token='other-worker'))
    assert result['boards']==0 and result['lease_lost'] and result['worker_errors']==1
    assert result['remaining_source_ids']==ids


def test_existing_lease_skips_tick_without_claiming_job_or_refreshing_heartbeat(factory,monkeypatch):
    seed_sources(factory,1)
    with factory() as db:
        token=jobs._claim_worker_lease(db,NOW)
        queued=jobs.enqueue(db)
        db.add(Setting(key='worker_heartbeat',value={'at':(NOW-timedelta(hours=3)).isoformat()}));db.commit()
    monkeypatch.setattr(jobs,'utcnow',lambda:NOW)
    assert jobs.run_tick()['status']=='already_running'
    with factory() as db:
        assert db.get(jobs.BackgroundJob,queued['job_id']).status=='pending'
        assert db.get(Setting,'worker_heartbeat').value['at']==(NOW-timedelta(hours=3)).isoformat()
        assert jobs._lease_owned(db,token,NOW)


@pytest.mark.skipif(not os.getenv('TEST_POSTGRES_URL'),reason='Requires isolated CI PostgreSQL service')
def test_postgres_concurrent_lease_claim_has_exactly_one_owner():
    from sqlalchemy import delete
    engine=create_engine(os.environ['TEST_POSTGRES_URL'])
    assert engine.dialect.name=='postgresql' and engine.url.host in {'localhost','127.0.0.1','postgres'}
    Base.metadata.create_all(engine);factory=sessionmaker(bind=engine,expire_on_commit=False)
    # The isolated test database has no application worker. Never run against a
    # hosted database, and clean only this dedicated worker lease row.
    with factory() as db:
        db.execute(delete(jobs.WorkerLease).where(jobs.WorkerLease.name=='collection'));db.commit()
    barrier=threading.Barrier(2)
    def claim():
        with factory() as db:
            barrier.wait(timeout=5);return jobs._claim_worker_lease(db,NOW)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            tokens=list(executor.map(lambda _:claim(),range(2)))
        assert sum(bool(token) for token in tokens)==1
    finally:
        with factory() as db:
            db.execute(delete(jobs.WorkerLease).where(jobs.WorkerLease.name=='collection'));db.commit()
        engine.dispose()
