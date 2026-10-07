"""The CI PostgreSQL service verifies locking and JSON-bearing retirement rows."""
import os
import pytest
from sqlalchemy import create_engine,select
from sqlalchemy.orm import Session
from internshipos.db import Base
from internshipos.models import JobSource
from internshipos.source_repairs import apply_endpoint_repairs,retire_replaced_sources,backfill_scoped_health
from test_domain import source,ingest
from test_source_repairs import manifest,replacement


@pytest.mark.skipif(not os.getenv('TEST_POSTGRES_URL'),reason='Requires isolated CI PostgreSQL service')
def test_postgres_endpoint_retirement_and_historical_scope_proof():
    # Only an explicitly named test database is accepted; production DATABASE_URL
    # is never used. Fixture records are rolled back after nested commits.
    engine=create_engine(os.environ['TEST_POSTGRES_URL'])
    assert engine.dialect.name=='postgresql'
    Base.metadata.create_all(engine)
    with engine.connect() as connection:
        transaction=connection.begin()
        with Session(bind=connection,expire_on_commit=False,join_transaction_mode='create_savepoint') as db:
            old=source(db); ingest(db,old)
            apply_endpoint_repairs(db,manifest(old)); new=replacement(db,old)
            ingest(db,new,jobs=[],inventory_complete=True,complete=True)
            assert retire_replaced_sources(db,new.id)==1
            assert not old.enabled and old.status=='superseded'
            assert db.scalar(select(JobSource).where(JobSource.company_source_id==old.id)).opportunity.status=='needs_recheck'
            assert retire_replaced_sources(db,new.id)==0
            target=source(db,provider='workday',name='Scoped fixture')
            ingest(db,target,coverage_scope='query')
            clock=target.config['board_checked_at']; target.config={'board_checked_at':clock}
            target.status='partial'; db.commit()
            assert backfill_scoped_health(db)==1 and target.config['board_checked_at']==clock
        transaction.rollback()
    engine.dispose()
