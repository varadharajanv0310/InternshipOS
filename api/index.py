"""Vercel Python API entry point; collection runs separately in scheduled CI."""
import os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
os.environ.setdefault('SCHEDULER_ENABLED','false')
os.environ.setdefault('APP_DATA_DIR','/tmp/internshipos')
if os.getenv('VERCEL')=='1':
    if not all(os.getenv(k) for k in ('DATABASE_URL','OWNER_PASSWORD','AUTH_SECRET','TOKEN_ENCRYPTION_KEY')):
        raise RuntimeError('Hosted API requires PostgreSQL and owner authentication secrets.')
    if not os.environ['DATABASE_URL'].startswith(('postgres://','postgresql://','postgresql+psycopg://')):
        raise RuntimeError('Hosted API requires PostgreSQL persistence.')
from internshipos.main import app
