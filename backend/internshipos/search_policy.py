"""Explicit discovery targets for this owner's technical internship search."""
from urllib.parse import urlencode
import re
from .domain import classify

SEARCH_TERMS = (
    'software engineer intern', 'backend developer intern', 'frontend developer intern',
    'full stack intern', 'data science intern', 'data engineer intern',
    'machine learning intern', 'AI intern', 'NLP intern', 'research intern',
)
TITLE_EXCLUSIONS = r'\b(?:wordpress|manual testing|manual qa|it support|help ?desk|service desk|ui/ux|ux design|ui design|graphic design|3d artist)\b'

def retain_new_candidate(job):
    result=classify(job.get('description',''),job.get('title',''))
    if result['role_family'] not in {'SWE','Data','AI_ML'} or result['opportunity_type'] not in {'internship','possible_internship','apprenticeship'}:return False
    if re.search(TITLE_EXCLUSIONS,job.get('title',''),re.I):return False
    country=str(job.get('country') or '').lower()
    location=str(job.get('location') or '')
    if country in {'in','ind','india'}:return True
    if country and country not in {'unknown','none'}:return False
    if re.search(r'\b(india|bengaluru|bangalore|chennai|hyderabad|mumbai|pune|delhi|noida|gurugram|gurgaon|kolkata|coimbatore|kochi|thiruvananthapuram|mysuru|mangaluru|trivandrum|chandigarh|jaipur|indore|ahmedabad)\b',location,re.I):return True
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
