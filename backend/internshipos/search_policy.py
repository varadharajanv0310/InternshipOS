"""Explicit discovery targets for this owner's technical internship search."""
from urllib.parse import urlencode
import re
from .domain import classify

SEARCH_TERMS = (
    'software engineer intern', 'backend developer intern', 'frontend developer intern',
    'full stack intern', 'data science intern', 'data engineer intern',
    'machine learning intern', 'AI intern', 'NLP intern', 'research intern',
    'SDE intern', 'software engineering internship', 'research assistant',
    'software apprentice',
)
TITLE_EXCLUSIONS = r'\b(?:wordpress|manual testing|manual qa|it support|help ?desk|service desk|product manager|managed services|cloudops|cloud ops|ui/ux|ux design|ui design|graphic design|3d artist|financial analyst|investment analyst|gtm|go.to.market|business strategy)\b'
PHD_ONLY = r'\b(?:ph\.?d\.?|doctoral)\b'
PRIMARY_CITIES = r'\b(?:bengaluru|bangalore|chennai)\b'
OTHER_CITIES = r'\b(?:hyderabad|mumbai|pune|delhi|noida|gurugram|gurgaon|kolkata|coimbatore|kochi|thiruvananthapuram|mysuru|mangaluru|trivandrum|chandigarh|jaipur|indore|ahmedabad|san francisco|new york|london|paris|singapore|seattle|austin|toronto)\b'

def location_decision(location='',country='',work_mode=''):
    location=str(location or '').lower(); country=str(country or '').lower()
    if re.search(PRIMARY_CITIES,location):return 'allowed'
    if country and country not in {'in','ind','india','unknown','none'}:return 'excluded'
    remote=('remote' in location or str(work_mode).lower()=='remote') and 'hybrid' not in location
    if remote and (country in {'in','ind','india'} or re.search(r'\bindia\b',location)):
        return 'allowed'
    if re.search(OTHER_CITIES,location):return 'excluded'
    clean=re.sub(r'[^a-z ]',' ',location).strip()
    if clean in {'india','in','remote india','india remote'}:return 'allowed'
    if not clean and country in {'in','ind','india'}:return 'allowed'
    return 'review'

def sql_pattern(pattern):
    # PostgreSQL uses different word-boundary escapes from Python/SQLite.
    return '(^|[^a-z])'+pattern[2:-2]+'([^a-z]|$)' if pattern.startswith(r'\b') and pattern.endswith(r'\b') else pattern

def target_sql(op):
    """Use exactly the Python policy in SQLite and PostgreSQL queries."""
    from sqlalchemy import case,func
    loc=func.lower(func.coalesce(op.location,''));country=func.lower(func.coalesce(op.country,''))
    remote=loc.like('%remote%') | (func.lower(op.work_mode)=='remote')
    return case(
        (loc.regexp_match(sql_pattern(PRIMARY_CITIES)),'allowed'),
        (~country.in_(['','in','ind','india','unknown','none']),'excluded'),
        (remote & ~loc.like('%hybrid%') & (country.in_(['in','ind','india']) | loc.regexp_match(r'(^|[^a-z])india([^a-z]|$)')),'allowed'),
        (loc.regexp_match(sql_pattern(OTHER_CITIES)),'excluded'),
        (loc.regexp_match(r'^\s*(india|in|remote[ ,]+india|india[ ,]+remote)\s*$'),'allowed'),
        ((func.trim(loc)=='') & country.in_(['in','ind','india']),'allowed'),else_='review')=='allowed'

def retain_new_candidate(job):
    result=classify(job.get('description',''),job.get('title',''))
    if result['opportunity_type']=='other' and 'intern' in str(job.get('employment_type') or '').lower():
        result['opportunity_type']='internship'
    if result['role_family'] not in {'SWE','Data','AI_ML'} or result['opportunity_type'] not in {'internship','possible_internship','apprenticeship'}:return False
    if re.search(TITLE_EXCLUSIONS,job.get('title',''),re.I):return False
    if re.search(PHD_ONLY,job.get('title',''),re.I):return False
    country=str(job.get('country') or '').lower()
    location=str(job.get('location') or '')
    decision=location_decision(location,country,job.get('work_mode',''))
    if decision=='allowed':return True
    if decision=='excluded':return False
    # Unknown/global remote eligibility remains a lead for review, never assumed
    # eligible for India. Known foreign location strings are not persisted anew.
    return not location.strip() or location.strip().lower() in {'remote','worldwide','global remote','unknown'}

def expanded_sources():
    sources=[]
    for provider,base in [('linkedin','https://www.linkedin.com/jobs/search/'),('indeed','https://in.indeed.com/jobs')]:
        for term in SEARCH_TERMS:
            sources.append({'name':provider.title()+' India · '+term,'provider':provider,
                'url':base+'?'+urlencode({'keywords' if provider=='linkedin' else 'q':term,'location' if provider=='linkedin' else 'l':'India'}),
                'config':{'search_term':term,'location':'India','results_wanted':30,'target_policy':'technical-internships-v1'},
                'cadence_hours':24,'enabled':True})
    # Reuse the old project's category/Chennai/WFH approach with bounded detail
    # fetches; a category result is discovery, never a complete employer board.
    for category in ('software development','data science','machine learning','artificial intelligence','full stack development','backend development','frontend development','python%2Fdjango'):
        for market,slug in [('Chennai',f'{category}-internship-in-chennai'),('Remote India',f'work-from-home-{category}-internship')]:
            sources.append({'name':f'Internshala {category} · {market}','provider':'internshala',
                'url':f'https://internshala.com/internships/{slug}/','config':{'target_policy':'technical-internships-v1'},'cadence_hours':24,'enabled':True})
    for family in ('SWE','AI'):
        sources.append({'name':f'2027 {family} international tracker','provider':'github_tracker',
            'url':f'https://raw.githubusercontent.com/speedyapply/2027-{family}-College-Jobs/main/INTERN_INTL.md',
            'config':{'global_feed':True,'target_policy':'technical-internships-v1'},'cadence_hours':12,'enabled':True})
    return sources
