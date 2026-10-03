"""FastAPI runtime. Startup is idempotent; hosted APIs can disable the local scheduler."""
import logging, os, threading
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[2]/'.env')
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from .db import init_db, SessionLocal, engine
from .seed import seed_database
from .jobs import worker_loop
from .api import router, public

logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(name)s %(message)s')
stop=threading.Event()

@asynccontextmanager
async def lifespan(app):
    public_url=os.getenv('PUBLIC_BASE_URL','http://127.0.0.1:8000')
    if urlparse(public_url).hostname not in ('localhost','127.0.0.1','::1') and not (os.getenv('OWNER_PASSWORD') and os.getenv('AUTH_SECRET') and os.getenv('TOKEN_ENCRYPTION_KEY')):
        raise RuntimeError('Hosted installations require OWNER_PASSWORD, AUTH_SECRET and TOKEN_ENCRYPTION_KEY before startup.')
    if os.getenv('VERCEL') != '1':
        # Schema/seed updates run in the durable collection workflow, not every
        # serverless cold start. Hosted startup only opens the existing database.
        init_db()
        from .bootstrap import install_discovery_sources,update_managed_seed_filters,update_classification_rules,install_previous_board_candidates,install_previous_companies,install_owner_search_policy
        from .company_priority import install_priorities
        with SessionLocal() as db:
            seed_database(db);update_managed_seed_filters(db);update_classification_rules(db);install_discovery_sources(db);install_previous_board_candidates(db);install_previous_companies(db);install_priorities(db);install_owner_search_policy(db)
    stop.clear()
    if os.getenv('SCHEDULER_ENABLED','true').lower()=='true':threading.Thread(target=worker_loop,args=(stop,),daemon=True,name='internshipos-worker').start()
    yield
    stop.set()

app=FastAPI(title='InternshipOS',version='0.1.0',lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=os.getenv('ALLOWED_ORIGINS','http://localhost:5173,http://127.0.0.1:5173').split(','),allow_credentials=True,allow_methods=['GET','POST','PATCH','DELETE','OPTIONS'],allow_headers=['Content-Type','Authorization'])
app.include_router(public);app.include_router(router)

@app.get('/health')
@app.get('/api/health')
def health():
    from sqlalchemy import text
    with engine.connect() as connection:connection.execute(text('SELECT 1'))
    return {'status':'ok','database':engine.dialect.name,'scheduler':os.getenv('SCHEDULER_ENABLED','true'),'version':'0.1.0'}

@app.exception_handler(ValueError)
def validation_error(request:Request,exc:ValueError):return JSONResponse({'detail':str(exc)},status_code=422)
