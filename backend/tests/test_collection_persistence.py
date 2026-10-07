"""Confirmed PG aborts replay atomic batches; ambiguous failures stay failed."""
import asyncio
import copy
import os
from types import SimpleNamespace

import psycopg
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from internshipos import db as database, jobs, seed, service, source_repairs
from internshipos.db import Base
from internshipos.ingestion import CollectionResult
from internshipos.models import Company, CompanySource, Setting


def pg_error(code, invalidated=False):
    original = psycopg.errors.lookup(code)('Injected transaction failure')
    return OperationalError('fixture statement', {}, original, connection_invalidated=invalidated)


class SessionAdapter:
    """Inject PG diagnostics while exercising real local SQL rollback/commit."""
    def __init__(self, session, dialect='postgresql'):
        self.session, self.dialect = session, dialect
        self.rollbacks = 0

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name=self.dialect))

    def rollback(self):
        self.rollbacks += 1
        self.session.rollback()

    def __getattr__(self, name):
        return getattr(self.session, name)

    def __enter__(self):
        self.session.__enter__()
        return self

    def __exit__(self, *args):
        return self.session.__exit__(*args)


@pytest.fixture
def local_engine():
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.mark.parametrize('code', ['40P01', '40001'])
def test_confirmed_abort_rolls_back_partial_writes_before_success(local_engine, monkeypatch, code):
    waits = []
    monkeypatch.setattr(jobs.time, 'sleep', waits.append)
    with Session(local_engine) as session:
        db = SessionAdapter(session)
        attempts = []
        def operation():
            attempts.append(len(attempts) + 1)
            db.add(Setting(key='attempt-' + str(len(attempts)), value={'attempt': len(attempts)}))
            db.flush()
            if len(attempts) == 1:
                raise pg_error(code)
            db.commit()
            return 'committed'
        value, retries = jobs._persist_transaction(db, operation, source_id='fixture', stage='ingest')
        assert value == 'committed' and retries == 1 and db.rollbacks == 1
        assert waits == [0.1]
        assert db.get(Setting, 'attempt-1') is None
        assert db.get(Setting, 'attempt-2').value == {'attempt': 2}


def test_abort_retries_are_bounded_and_exhaustion_preserves_no_partial_writes(local_engine, monkeypatch):
    waits = []
    monkeypatch.setattr(jobs.time, 'sleep', waits.append)
    with Session(local_engine) as session:
        db = SessionAdapter(session)
        attempts = []
        def operation():
            attempts.append(True)
            db.add(Setting(key='partial-' + str(len(attempts)), value=True)); db.flush()
            raise pg_error('40P01')
        with pytest.raises(OperationalError):
            jobs._persist_transaction(db, operation, source_id='fixture', stage='ingest')
        assert len(attempts) == db.rollbacks == 3 and waits == [0.1, 0.2]
        assert db.scalars(select(Setting)).all() == []


@pytest.mark.parametrize('error,dialect', [
    (pg_error('40P01'), 'sqlite'),
    (pg_error('40001'), 'mysql'),
    (pg_error('23505'), 'postgresql'),
    (pg_error('08006'), 'postgresql'),
    (pg_error('40P01', invalidated=True), 'postgresql'),
    (RuntimeError('network status unknown'), 'postgresql'),
])
def test_other_database_unknown_or_ambiguous_failures_are_not_replayed(local_engine, monkeypatch, error, dialect):
    monkeypatch.setattr(jobs.time, 'sleep', lambda delay: pytest.fail('Nonretryable failures must not sleep'))
    with Session(local_engine) as session:
        db = SessionAdapter(session, dialect=dialect)
        attempts = []
        def operation():
            attempts.append(True)
            db.add(Setting(key='partial', value=True)); db.flush()
            raise error
        with pytest.raises(type(error)):
            jobs._persist_transaction(db, operation, source_id='fixture', stage='ingest')
        assert len(attempts) == db.rollbacks == 1 and db.get(Setting, 'partial') is None


def test_collector_replays_same_batch_and_retries_retirement_separately(local_engine, monkeypatch):
    factory = sessionmaker(bind=local_engine, expire_on_commit=False)
    with factory() as db:
        employer = Company(name='Fixture'); db.add(employer); db.flush()
        source = CompanySource(company_id=employer.id, provider='fixture', url='https://example.com/jobs', enabled=True)
        db.add(source); db.commit(); source_id = source.id
    monkeypatch.setattr(jobs, 'SessionLocal', lambda: SessionAdapter(factory()))
    monkeypatch.setattr(jobs.time, 'sleep', lambda delay: None)
    monkeypatch.setenv('COLLECTION_TARGET_ONLY', 'false')
    monkeypatch.setenv('COLLECTION_CONCURRENCY', '1')
    original = CollectionResult(jobs=[{'external_id':'1', 'title':'Software Intern'}], complete=True,
        metadata={'inventory_complete':True, 'nested':{'proof':'original'}})
    async def collect(*args, **kwargs):
        return original
    monkeypatch.setattr('internshipos.ingestion.collect_source', collect)
    seen_batches, ingest_calls, retire_calls = [], [], []
    def ingest(db, ident, batch, **kwargs):
        ingest_calls.append(True); seen_batches.append((copy.deepcopy(batch), copy.deepcopy(kwargs['collection_metadata'])))
        db.add(Setting(key='ingest-' + str(len(ingest_calls)), value=True)); db.flush()
        if len(ingest_calls) == 1:
            batch[0]['title'] = 'Mutated failed copy'
            kwargs['collection_metadata']['nested']['proof'] = 'changed'
            raise pg_error('40001')
        db.commit()
        return {'source_id':ident, 'status':'complete'}
    def retire(db, ident):
        retire_calls.append(True)
        db.add(Setting(key='retire-' + str(len(retire_calls)), value=True)); db.flush()
        if len(retire_calls) == 1:
            raise pg_error('40P01')
        db.commit()
        return 0
    monkeypatch.setattr(service, 'ingest_batch', ingest)
    monkeypatch.setattr(source_repairs, 'retire_replaced_sources', retire)
    result = asyncio.run(jobs.collect_boards([source_id], force=True))
    assert result['worker_errors'] == 0 and result['results'][0]['persistence_retries'] == {'ingest':1, 'retire':1}
    assert len(ingest_calls) == len(retire_calls) == 2 and seen_batches[0] == seen_batches[1]
    assert original.jobs[0]['title'] == 'Software Intern' and original.metadata['nested']['proof'] == 'original'
    with factory() as db:
        assert set(db.scalars(select(Setting.key)).all()) == {'ingest-2', 'retire-2'}


@pytest.mark.parametrize('result,expected', [
    ({'boards':48, 'worker_errors':1}, 1),
    ({'status':'failed', 'detail':'Persistence failed'}, 1),
    ({'boards':48, 'worker_errors':0, 'statuses':{'error':20,'partial':28}}, 0),
    ({'status':'already_running'}, 0),
])
def test_tick_exit_reports_worker_failure_without_failing_public_source_errors(monkeypatch, capsys, result, expected):
    class SeedSession:
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr(database, 'init_db', lambda: None)
    monkeypatch.setattr(seed, 'seed_database', lambda db: None)
    monkeypatch.setattr(jobs, 'SessionLocal', SeedSession)
    monkeypatch.setattr(jobs, 'run_tick', lambda force: result)
    assert jobs.main(['tick']) == expected
    assert str(result) in capsys.readouterr().out


@pytest.mark.skipif(not os.getenv('TEST_POSTGRES_URL'), reason='Requires isolated CI PostgreSQL service')
@pytest.mark.parametrize('code', ['40P01', '40001'])
def test_real_postgres_server_abort_retries_inside_isolated_transaction(monkeypatch, code):
    engine = create_engine(os.environ['TEST_POSTGRES_URL'])
    assert engine.dialect.name == 'postgresql' and engine.url.host in {'localhost','127.0.0.1','postgres'}
    Base.metadata.create_all(engine)
    monkeypatch.setattr(jobs.time, 'sleep', lambda delay: None)
    try:
        with engine.connect() as connection:
            outer = connection.begin()
            with Session(bind=connection, expire_on_commit=False, join_transaction_mode='create_savepoint') as db:
                attempts = []
                key = 'pg-retry-fixture-' + __import__('uuid').uuid4().hex
                def operation():
                    attempts.append(True)
                    db.add(Setting(key=key + '-' + str(len(attempts)), value=True)); db.flush()
                    if len(attempts) == 1:
                        db.execute(text("DO $$ BEGIN RAISE EXCEPTION 'retry fixture' USING ERRCODE = '" + code + "'; END; $$"))
                    db.commit()
                    return 'success'
                value, retries = jobs._persist_transaction(db, operation, source_id='fixture', stage='ingest')
                assert value == 'success' and retries == 1 and len(attempts) == 2
                assert db.get(Setting, key + '-1') is None and db.get(Setting, key + '-2') is not None
            outer.rollback()
    finally:
        engine.dispose()
