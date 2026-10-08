"""Immutable factual resume versions, public GitHub inventory and application packs."""
import base64, hashlib, html, io, json, os, re
from pathlib import Path
from datetime import datetime, timezone
import httpx
from fastapi import HTTPException
from sqlalchemy import select
from .models import Resume, ResumeVersion, ResumeArtifact, Project, Integration, Activity, Application
from .serialize import row_dict
from . import service

def resume_inventory(db):
    items=[]
    for resume in db.scalars(select(Resume).order_by(Resume.created_at.desc())).all():
        item=row_dict(resume);versions=db.scalars(select(ResumeVersion).where(ResumeVersion.resume_id==resume.id).order_by(ResumeVersion.created_at.desc())).all();item['versions']=[{**row_dict(v),'title':v.data.get('title',resume.name),'version_number':len(versions)-i} for i,v in enumerate(versions)];items.append(item)
    github=db.scalars(select(Integration).where(Integration.provider=='github')).first()
    return {'items':items,'total':len(items),'projects':[row_dict(p) for p in db.scalars(select(Project).order_by(Project.name)).all()], 'github':{'connected':bool(github and github.status=='public_inventory'),'status':github.status if github else 'disconnected','data':github.data if github else {}},'upload_max_bytes':UPLOAD_MAX_BYTES}

UPLOAD_MAX_BYTES=3*1024*1024

def upload_resume(db,contents,filename,name='',role_focus='general',resume_id=''):
    """Validate once, store the exact PDF separately from immutable version facts."""
    if len(contents)>UPLOAD_MAX_BYTES:raise HTTPException(413,'Choose a PDF smaller than 3 MB.')
    filename=re.split(r'[/\\]',filename or 'resume.pdf')[-1]
    filename=''.join(c for c in filename if c.isprintable())[:200]
    if not filename.lower().endswith('.pdf') or not contents.startswith(b'%PDF-'):raise HTTPException(422,'Upload a PDF resume.')
    from pypdf import PdfReader
    try:
        reader=PdfReader(io.BytesIO(contents))
        if reader.is_encrypted:raise ValueError('encrypted')
        pages=len(reader.pages)
        if not 1<=pages<=30:raise ValueError('page count')
    except Exception as exc:raise HTTPException(422,'Choose a readable PDF with 1–30 pages and no password.') from exc
    resume=db.get(Resume,resume_id) if resume_id else None
    if resume_id and not resume:raise HTTPException(404,'Resume variant not found.')
    if not resume:
        resume=Resume(name=(name.strip() or filename[:-4])[:300],role_focus=role_focus[:100] or 'general',data={});db.add(resume);db.flush()
    version=ResumeVersion(resume_id=resume.id,data={'source':'upload','title':name.strip()[:300] or filename[:-4],'filename':filename,'bytes':len(contents),'pages':pages,'role_focus':resume.role_focus},status='draft',artifact_hash=hashlib.sha256(contents).hexdigest())
    db.add(version);db.flush();db.add(ResumeArtifact(version_id=version.id,contents=contents))
    db.add(Activity(kind='resume_upload',title='Original resume uploaded',entity_type='resume_version',entity_id=version.id,data={'resume_id':resume.id,'sha256':version.artifact_hash}));db.commit()
    return row_dict(version)

def approve_upload(db,version):
    if version.data.get('source')!='upload' or not db.get(ResumeArtifact,version.id):raise HTTPException(422,'This is not an uploaded resume.')
    version.status='approved'
    db.add(Activity(kind='resume_review',title='Uploaded resume approved for applications',entity_type='resume_version',entity_id=version.id));db.commit();return row_dict(version)

def facts_inventory(db):
    profile=service.get_profile(db);facts=[]
    for key,value in profile.items():
        if value and key not in ('id','created_at','version','sensitive_answers','address','authorization_answers'):
            facts.append({'id':'profile:'+key,'field':key,'value':value})
    for p in db.scalars(select(Project).where(Project.approved==True)).all():
        facts.append({'id':'project:'+p.id,'name':p.name,'technologies':p.technologies,'description':p.description,'bullets':p.approved_bullets,'url':p.github_url})
    return facts

def create_resume(db,payload):
    name=str(payload.get('name','')).strip()
    if not name:raise HTTPException(422,'Give this resume variant a name.')
    resume=Resume(name=name[:300],role_focus=payload.get('role_focus','general'),data={});db.add(resume);db.commit();return row_dict(resume)

def create_version(db,resume_id,payload):
    resume=db.get(Resume,resume_id)
    if not resume:raise HTTPException(404,'Resume variant not found.')
    profile=service.get_profile(db)
    if not (profile.get('name') or profile.get('display_name')):raise HTTPException(422,'Add your name and factual profile in Settings before creating a resume.')
    ids=payload.get('selected_project_ids',[])
    projects=db.scalars(select(Project).where(Project.id.in_(ids))).all() if ids else []
    if len(projects)!=len(set(ids)) or any(not p.approved for p in projects):raise HTTPException(422,'Only reviewed, approved projects may be included in a resume.')
    # All generated versions use the exact approved fact text, never unchecked model prose.
    available=[b for p in projects for b in p.approved_bullets]+list(profile.get('approved_bullets',[]))
    supplied=payload.get('bullets',[])
    if any(b not in available for b in supplied):raise HTTPException(422,'A bullet is not in your approved fact inventory. Review and save it as a factual profile/project bullet first.')
    data={'profile':{k:v for k,v in profile.items() if k not in ('address','sensitive_answers','authorization_answers')},'projects':[row_dict(p) for p in projects],'bullets':supplied or list(profile.get('approved_bullets',[])),'title':str(payload.get('title',resume.name)),'role_focus':resume.role_focus,'facts':facts_inventory(db),'template':'reviewed-v1','selected_project_ids':ids,'parent_version_id':payload.get('parent_version_id')}
    version=ResumeVersion(resume_id=resume.id,data=data,status='approved');db.add(version);db.flush()
    version.artifact_hash=hashlib.sha256(json.dumps(data,sort_keys=True,default=str).encode()).hexdigest()
    db.add(Activity(kind='resume_version',title='Resume version created',entity_type='resume_version',entity_id=version.id,data={'resume_id':resume.id,'fact_hash':version.artifact_hash}));db.commit();return row_dict(version)

def render_html(version):
    data=version.data;profile=data.get('profile',{});e=lambda s:html.escape(str(s or ''))
    name=profile.get('name') or profile.get('display_name') or 'Resume'
    contacts=[profile.get('email'),profile.get('phone'),profile.get('location'),profile.get('github_url'),profile.get('linkedin_url')]
    education=profile.get('education') or profile.get('degree') or ''
    if isinstance(education,dict):
        details=education
        education=' · '.join(str(details[k]) for k in ('degree','branch','university') if details.get(k))
        profile={**details,**profile}
    elif isinstance(education,list):education='; '.join(' · '.join(str(v) for v in item.values() if v) if isinstance(item,dict) else str(item) for item in education)
    graduation=profile.get('graduation_year') or profile.get('graduation_date')
    skills=profile.get('skills',[]);skills=', '.join(skills) if isinstance(skills,list) else skills
    parts=[f'<header><h1>{e(name)}</h1><p>{e(" · ".join(str(x) for x in contacts if x))}</p></header>']
    if education:parts.append(f'<section><h2>Education</h2><p><strong>{e(education)}</strong> {e(profile.get("branch"))}</p><p>{e(profile.get("university"))} {e(graduation)} {" · CGPA "+e(profile.get("cgpa")) if profile.get("cgpa") else ""}</p></section>')
    if skills:parts.append(f'<section><h2>Technical skills</h2><p>{e(skills)}</p></section>')
    if data.get('bullets'):parts.append('<section><h2>Experience and achievements</h2><ul>'+''.join('<li>'+e(b)+'</li>' for b in data['bullets'])+'</ul></section>')
    if data.get('projects'):
        items=[]
        for p in data['projects']:
            items.append(f'<article><h3>{e(p["name"])} <small>{e(" · ".join(p.get("technologies",[])))}</small></h3><p>{e(p.get("description"))}</p><ul>'+''.join('<li>'+e(b)+'</li>' for b in p.get('approved_bullets',[]))+f'</ul><p class="link">{e(p.get("github_url"))}</p></article>')
        parts.append('<section><h2>Projects</h2>'+''.join(items)+'</section>')
    return '<!doctype html><html><head><meta charset="utf-8"><title>'+e(data.get('title'))+'</title><style>@page{size:A4;margin:18mm}*{box-sizing:border-box}body{font:10.5pt/1.45 Arial,Helvetica,sans-serif;color:#17212e;margin:0}h1{font-size:25pt;letter-spacing:-.7px;margin:0 0 4px}header{border-bottom:2px solid #223349;padding-bottom:12px;margin-bottom:18px}h2{font-size:11pt;text-transform:uppercase;letter-spacing:1px;border-bottom:1px solid #dae0e6;padding-bottom:5px;margin:18px 0 8px}h3{font-size:11pt;margin:10px 0 4px}small{font-weight:normal;font-size:9pt;color:#526375}p{margin:4px 0}ul{margin:6px 0;padding-left:18px}li{margin:3px 0}.link{font-size:9pt;color:#526375}article{break-inside:avoid}header p{font-size:9pt}a{color:inherit}</style></head><body>'+''.join(parts)+'</body></html>'

def pdf_artifact(db,version):
    folder=Path(os.getenv('APP_DATA_DIR','data'))/'resumes';folder.mkdir(parents=True,exist_ok=True)
    path=folder/(version.id+'.pdf')
    if version.data.get('source')=='upload':
        original=db.get(ResumeArtifact,version.id)
        if not original:raise HTTPException(404,'Original uploaded PDF is unavailable. Upload it again.')
        path.write_bytes(original.contents)
        return path
    if path.exists() and version.artifact_path:return path
    try:
        if os.getenv('PDF_ENGINE','').lower()=='reportlab' or os.getenv('VERCEL'):
            render_portable_pdf(version,path)
        else:
            render_browser_pdf(version,path)
    except Exception:
        # A free/serverless runtime does not need a Chromium installation.
        try:render_portable_pdf(version,path)
        except Exception as exc:raise HTTPException(503,'PDF rendering failed; the HTML preview and structured facts remain available. '+str(exc)[:120]) from exc
    version.artifact_path=str(path.resolve());version.artifact_hash=hashlib.sha256(path.read_bytes()).hexdigest();db.commit();return path

def render_browser_pdf(version,path):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        executable=os.getenv('PDF_BROWSER_EXECUTABLE')
        if not executable:
            for candidate in ['C:/Program Files/Google/Chrome/Application/chrome.exe','C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe']:
                if Path(candidate).exists():executable=candidate;break
        browser=p.chromium.launch(headless=True,**({'executable_path':executable} if executable else {}))
        try:
            page=browser.new_page();page.set_content(render_html(version),wait_until='load');page.pdf(path=str(path),format='A4',print_background=True,prefer_css_page_size=True)
        finally:browser.close()

def render_portable_pdf(version,path):
    from bs4 import BeautifulSoup
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,HRFlowable
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    font='Helvetica'
    candidates=[os.getenv('PDF_FONT_REGULAR',''),'C:/Windows/Fonts/arial.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            if 'ResumeRegular' not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(TTFont('ResumeRegular',candidate))
            font='ResumeRegular';break
    styles=getSampleStyleSheet()
    for style in styles.byName.values():style.fontName=font;style.textColor=colors.HexColor('#17212e')
    styles['Normal'].fontSize=10;styles['Normal'].leading=14
    styles['Heading1'].fontSize=23;styles['Heading1'].leading=29
    styles['Heading2'].fontSize=11;styles['Heading2'].spaceBefore=14
    styles['Heading3'].fontSize=10.5
    soup=BeautifulSoup(render_html(version),'html.parser');story=[]
    for node in soup.body.find_all(['h1','h2','h3','p','li']):
        value=html.escape(node.get_text(' ',strip=True))
        style=styles[{'h1':'Heading1','h2':'Heading2','h3':'Heading3'}.get(node.name,'Normal')]
        story.append(Paragraph(('• ' if node.name=='li' else '')+value,style))
        if node.name=='h2':story.append(HRFlowable(width='100%',thickness=.5,color=colors.HexColor('#dae0e6')))
        story.append(Spacer(1,2*mm if node.name!='li' else mm))
    SimpleDocTemplate(str(path),pagesize=A4,rightMargin=18*mm,leftMargin=18*mm,topMargin=17*mm,bottomMargin=17*mm,title=version.data.get('title','Resume'),author=version.data.get('profile',{}).get('display_name','')).build(story)

def github_inventory(db,username):
    from concurrent.futures import ThreadPoolExecutor
    from urllib.parse import quote
    username=username.strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}',username):raise HTTPException(422,'Enter a valid GitHub username.')
    headers={'Accept':'application/vnd.github+json','User-Agent':'InternshipOS/0.1'}
    token=os.getenv('GITHUB_TOKEN')
    if token:headers['Authorization']='Bearer '+token
    repositories=[]
    try:
        with httpx.Client(timeout=15,headers=headers) as client:
            for page in range(1,21):
                response=client.get(f'https://api.github.com/users/{username}/repos',params={'per_page':100,'sort':'updated','type':'owner','page':page})
                if response.status_code==404:raise HTTPException(404,'This GitHub user was not found.')
                if response.status_code in (403,429):raise HTTPException(429,'GitHub is limiting requests. Your previous projects are kept; try syncing later.')
                response.raise_for_status();batch=response.json()
                repositories.extend(r for r in batch if not r.get('fork') and not r.get('archived'))
                if len(batch)<100:break
            else:raise HTTPException(422,'This account exceeds the 2,000 repository import limit. Your previous connection is kept.')
            def read_readme(repo):
                try:
                    result=client.get('https://api.github.com/repos/'+quote(username,safe='')+'/'+quote(repo['name'],safe='')+'/readme')
                    return result.json() if result.status_code==200 else {}
                except (httpx.HTTPError,ValueError):return {}
            with ThreadPoolExecutor(max_workers=4) as pool:
                readmes=list(pool.map(read_readme,repositories[:12]))
    except (httpx.HTTPError,ValueError) as exc:
        raise HTTPException(503,'GitHub could not be reached. Your previous connection and projects are kept. Try again shortly.') from exc
    timestamp=datetime.now(timezone.utc).isoformat()
    for index,repo in enumerate(repositories):
        url='https://github.com/'+repo.get('owner',{}).get('login',username)+'/'+repo['name']
        project=db.scalars(select(Project).where(Project.github_url==url)).first()
        technologies=[repo['language']] if repo.get('language') else []
        if not project:
            project=Project(name=repo['name'],github_url=url,description=repo.get('description') or '',technologies=technologies,approved=False,approved_bullets=[],role_tags=[],data={});db.add(project);db.flush()
        project.data={**project.data,'github_id':repo['id'],'github_username':username,'updated_at':repo.get('updated_at'),'stars':repo.get('stargazers_count',0),'topics':repo.get('topics',[]),'imported_at':timestamp,'source':'GitHub API','features_need_review':not project.approved}
        detail=readmes[index] if index<len(readmes) else {}
        if detail.get('encoding')=='base64' and detail.get('size',0)<=100000:
            try:text=base64.b64decode(detail.get('content','')).decode(errors='replace')[:16000]
            except (ValueError,TypeError):text=''
            claims=[re.sub(r'^\s*[-*+]\s+','',line).strip() for line in text.splitlines() if re.match(r'^\s*[-*+]\s+\S',line)][:30]
            project.data={**project.data,'readme_url':detail.get('html_url'),'readme_excerpt':text,'unreviewed_feature_claims':claims,'measurable_claims_require_review':True}
    row=db.scalars(select(Integration).where(Integration.provider=='github')).first()
    if not row:row=Integration(provider='github');db.add(row)
    row.status='public_inventory';row.data={'username':username,'last_imported_at':timestamp,'repositories':len(repositories),'scope':'public repositories','readmes_imported':sum(bool(x) for x in readmes)}
    db.add(Activity(kind='github_import',title=f'Imported {len(repositories)} GitHub projects',data={'username':username,'approval_required':True}));db.commit()
    return {'imported':len(repositories),'projects':resume_inventory(db)['projects'],'note':'Review actual features and approve factual bullets before using these projects in a resume.'}

def preparation_pack(db,application_id):
    application=service.list_applications(db)['items'];app=next((a for a in application if a['id']==application_id),None)
    if not app:raise HTTPException(404,'Application not found.')
    op=app['opportunity'];profile=service.get_profile(db);required=op.get('requirements',[]);inventory=resume_inventory(db)
    readiness=op.get('shortlist') or {'preparation_allowed':False,'review_reasons':['Refresh and review the original posting.']}
    recommended=[]
    for p in inventory['projects']:
        if p['approved']:
            overlap=len(set(t.lower() for t in p.get('technologies',[])) & set(s.lower() for s in op.get('skills',[])))
            recommended.append({**p,'matched_skills':overlap})
    recommended.sort(key=lambda p:p['matched_skills'],reverse=True)
    versions=[v for r in inventory['items'] for v in r['versions'] if v['status']=='approved']
    version=next((v for v in versions if v['id']==app.get('resume_version_id')),None)
    if not version:
        role=op.get('role_family','').lower();variants=[r for r in inventory['items'] if r['role_focus'].lower() in role or role in r['role_focus'].lower()]
        version=next((v for r in variants for v in r['versions'] if v['status']=='approved'),versions[0] if versions else None)
    profile={**profile,**{k:v for k,v in (profile.get('education') or {}).items() if k not in profile}}
    fields={k:profile.get(k) for k in ('name','display_name','email','phone','github_url','linkedin_url','university','branch','graduation_year') if profile.get(k)}
    return {'application':app,'opportunity':op,'profile':profile,'fields':fields,'resume_version':version,'resume_download_url':'/api/resume-versions/'+version['id']+'/download' if version else None,'recommended_projects':recommended[:4],'requirements_checklist':required,'checklist':required,'unknowns':op.get('evaluation',{}).get('unknowns',[]),'readiness':readiness,'ready_to_prepare':readiness.get('preparation_allowed',False),'facts':facts_inventory(db),'answers':{'education':profile.get('education') or profile.get('degree'),'skills':', '.join(profile.get('skills',[])),'github':profile.get('github_url')},'sensitive_answers_local':True,'queue_approval':(app.get('data') or {}).get('auto_apply',{}),'requires_submission_lease':True,'submission_status':app['stage'],'auto_apply':service.get_settings(db).get('auto_apply',{'enabled':False,'providers':[]})}
