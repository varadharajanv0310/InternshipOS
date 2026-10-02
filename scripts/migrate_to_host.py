"""Copy the personal workspace to an EMPTY hosted DB; retain full local archive.

DATABASE_URL must name the new PostgreSQL destination. The source remains
data/internshipos.db. Foreign/unrelated unsaved jobs stay in the local archive.
"""
import sys,os,re,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from sqlalchemy import create_engine,select,func
from sqlalchemy.orm import Session
from internshipos.db import Base,engine
from internshipos import models as m,service
from internshipos.jobs import BackgroundJob
from internshipos.search_policy import TITLE_EXCLUSIONS

if engine.dialect.name!='postgresql':raise RuntimeError('Destination must be PostgreSQL')
source=create_engine('sqlite:///'+(Path(__file__).resolve().parents[1]/'data/internshipos.db').as_posix())
Base.metadata.create_all(engine)
with source.connect() as src,engine.begin() as dst,Session(source) as db:
 if any(dst.scalar(select(func.count()).select_from(t)) for t in Base.metadata.sorted_tables):raise RuntimeError('Destination must be empty; existing data is never overwritten')
 tracked=set(db.scalars(select(m.Application.opportunity_id)).all())
 selected={o.id for o in db.scalars(select(m.Opportunity)).all() if o.saved or o.id in tracked or (service._in_primary_market(o) and o.role_family in {'SWE','Data','AI_ML'} and o.opportunity_type in {'internship','possible_internship','apprenticeship'} and not re.search(TITLE_EXCLUSIONS,o.title,re.I))}
 retained={};counts={}
 for table in Base.metadata.sorted_tables:
  keep=[]
  for mapping in src.execute(select(table)).mappings():
   row=dict(mapping)
   if table.name=='opportunities' and row['id'] not in selected:continue
   if table.name=='activity' and row.get('entity_type')=='opportunity' and row.get('entity_id') not in selected:continue
   if table.name=='settings' and row.get('key','').startswith(('ai_cache:','digest:')):continue
   foreign=[(c.name,f.column.table.name) for c in table.c for f in c.foreign_keys]
   if any(row.get(col) is not None and row[col] not in retained.get(target,set()) for col,target in foreign):continue
   if table.name=='integrations':row.update(credentials_encrypted=None,status='disconnected',data={})
   if table.name=='background_jobs':row.update(status='interrupted')
   if table.name=='resume_versions':row['artifact_path']=None
   keep.append(row)
   if len(keep)>=100:dst.execute(table.insert(),keep);keep=[]
  if keep:dst.execute(table.insert(),keep)
  if 'id' in table.c:retained[table.name]=set(dst.scalars(select(table.c.id)).all())
  counts[table.name]=dst.scalar(select(func.count()).select_from(table))
  print(table.name,counts[table.name],flush=True)
 Path('data/private/hosting/migration-counts.json').write_text(json.dumps(counts,indent=2),encoding='utf-8')
print('Hosted migration committed; complete original local archive preserved.',flush=True)
