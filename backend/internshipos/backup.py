"""Portable owner backups; authentication/encryption keys are never bundled.

Restore into an empty database so existing application history cannot be overwritten.
"""
import hashlib, io, json, os, zipfile
from datetime import datetime
from pathlib import Path
from sqlalchemy import DateTime, func, select
from fastapi import HTTPException
from .db import Base, utcnow
from .models import Setting, Activity, ResumeVersion, ResumeArtifact
from .serialize import json_value

def backup_status(db):
    row=db.get(Setting,'backup_status')
    return {**(row.value if row else {}),'last_backup_at':(row.value or {}).get('at') if row else None,'format':'InternshipOS portable ZIP v1','credentials_included':False,'note':'Download a copy to another device. Google must be reconnected after restore.'}

def create_backup(db):
    folder=Path(os.getenv('APP_DATA_DIR','data'))/'backups';folder.mkdir(parents=True,exist_ok=True)
    manifest={'format':'InternshipOS','version':1,'created_at':utcnow().isoformat(),'tables':{},'artifacts':{}}
    for table in Base.metadata.sorted_tables:
        records=[]
        if table.name=='resume_artifacts':
            manifest['tables'][table.name]=[]
            continue
        for mapping in db.execute(select(table)).mappings():
            record=dict(mapping)
            record.pop('credentials_encrypted',None)
            if table.name=='settings' and record.get('key','').startswith(('ai_cache:','digest:')):continue
            if table.name=='integrations':record.update(status='disconnected',data={})
            if table.name=='background_jobs' and record.get('status') in ('running','pending'):record['status']='interrupted'
            records.append(json_value(record))
        manifest['tables'][table.name]=records
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
        for version in db.scalars(select(ResumeVersion)).all():
            uploaded=db.get(ResumeArtifact,version.id) if version.data.get('source')=='upload' else None
            source=Path(version.artifact_path) if version.artifact_path else None
            if uploaded or (source and source.is_file() and source.stat().st_size<=5_000_000):
                contents=uploaded.contents if uploaded else source.read_bytes();name='resumes/'+version.id+'.pdf';archive.writestr(name,contents)
                manifest['artifacts'][version.id]={'path':name,'sha256':hashlib.sha256(contents).hexdigest()}
        archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,default=str))
    contents=stream.getvalue();filename='internshipos-'+utcnow().strftime('%Y%m%d-%H%M%S-%f')+'.zip'
    path=folder/filename;path.write_bytes(contents)
    status={'at':manifest['created_at'],'filename':filename,'bytes':len(contents),'sha256':hashlib.sha256(contents).hexdigest(),'tables':len(manifest['tables'])}
    db.merge(Setting(key='backup_status',value=status));db.add(Activity(kind='backup',title='Workspace backup exported',data=status));db.commit()
    # Keep only ten local exports; a downloaded copy is independent of this rotation.
    for old in sorted(folder.glob('internshipos-*.zip'),key=lambda p:p.stat().st_mtime,reverse=True)[10:]:old.unlink()
    return path

def restore_backup(db,path):
    if any(db.scalar(select(func.count()).select_from(t)) for t in Base.metadata.sorted_tables):
        raise ValueError('Restore requires an empty database. Use a new DATABASE_URL; existing records are never overwritten.')
    with zipfile.ZipFile(path) as archive:
        if sum(i.file_size for i in archive.infolist())>250_000_000:raise ValueError('Backup exceeds the 250 MB restore limit.')
        manifest=json.loads(archive.read('manifest.json'))
        if manifest.get('format')!='InternshipOS' or manifest.get('version')!=1:raise ValueError('Unsupported backup format.')
        artifacts=[]
        for table in Base.metadata.sorted_tables:
            rows=manifest['tables'].get(table.name,[])
            for row in rows:
                for column in table.columns:
                    if isinstance(column.type,DateTime) and row.get(column.name):row[column.name]=datetime.fromisoformat(row[column.name].replace('Z','+00:00'))
                if table.name=='resume_versions':row['artifact_path']=None
                if table.name=='integrations':row.update(credentials_encrypted=None,status='disconnected',data={})
                if table.name=='settings' and row.get('key')=='auto_apply':row['value']={'enabled':False,'providers':[]}
                db.execute(table.insert().values(**{k:v for k,v in row.items() if k in table.c}))
        for version_id,info in manifest.get('artifacts',{}).items():
            version=db.get(ResumeVersion,version_id)
            if not version or info['path']!='resumes/'+version_id+'.pdf' or not all(c.isalnum() or c=='-' for c in version_id):raise ValueError('Invalid resume artifact identity.')
            contents=archive.read(info['path'])
            if hashlib.sha256(contents).hexdigest()!=info['sha256']:raise ValueError('Resume artifact checksum mismatch.')
            artifacts.append((version,contents))
        folder=Path(os.getenv('APP_DATA_DIR','data'))/'resumes';folder.mkdir(parents=True,exist_ok=True)
        for version,contents in artifacts:
            target=folder/(version.id+'.pdf');target.write_bytes(contents);version.artifact_path=str(target.resolve())
            if version.data.get('source')=='upload':db.add(ResumeArtifact(version_id=version.id,contents=contents))
        db.commit()
    return {'tables':len(manifest['tables']),'resumes':len(artifacts)}

if __name__=='__main__':
    import argparse
    from .db import init_db,SessionLocal
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['export','restore']);parser.add_argument('path',nargs='?');args=parser.parse_args()
    init_db()
    with SessionLocal() as db:
        print(create_backup(db) if args.command=='export' else restore_backup(db,args.path))
