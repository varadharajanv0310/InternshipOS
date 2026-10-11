"""Inference boundary. Paid compatible models require explicit prices.
OpenAI standard rates verified 2026-10-02: https://developers.openai.com/api/docs/pricing
"""
import json, os
from dataclasses import dataclass, field
from urllib.parse import urlparse
import httpx
from fastapi import HTTPException

SCHEMA={'type':'object','properties':{'text':{'type':'string'},'fact_ids':{'type':'array','items':{'type':'string'}},'unknowns':{'type':'array','items':{'type':'string'}}},'required':['text','fact_ids','unknowns'],'additionalProperties':False}
KNOWN_RATES={'gpt-6-luna':(.10,.50),'gpt-6.1-sol':(2.,10.)}
# DeepSeek peak/cache-miss rates are conservative reservation bounds.
# Verified 2026-10-11: https://api-docs.deepseek.com/quick_start/pricing/
DEEPSEEK_RATES={'deepseek-flash':(.30,1.20)}

@dataclass
class Provider:
    name:str
    model:str
    key:str=field(repr=False)
    base_url:str
    rates:tuple[float,float]
    max_output_tokens:int=2200

    def generate(self,instructions,prompt,max_tokens=None):
        max_tokens=self.max_output_tokens if max_tokens is None else max_tokens
        with httpx.Client(timeout=75) as client:
            headers={'Authorization':'Bearer '+self.key} if self.key else {}
            if self.name=='openai':
                response=client.post(self.base_url+'/responses',headers=headers,json={'model':self.model,'instructions':instructions,'input':prompt,'max_output_tokens':max_tokens,'service_tier':'default','store':False,'reasoning':{'effort':'low'},'text':{'format':{'type':'json_schema','name':'grounded_draft','strict':True,'schema':SCHEMA}}})
                response.raise_for_status();data=response.json();tokens=data.get('usage',{})
                output=''.join(p.get('text','') for item in data.get('output',[]) for p in item.get('content',[]) if p.get('type')=='output_text')
                return json.loads(output),tokens.get('input_tokens'),tokens.get('output_tokens')
            payload={'model':self.model,'messages':[{'role':'system','content':instructions},{'role':'user','content':prompt}],'max_tokens':max_tokens,'stream':False,'response_format':{'type':'json_schema','json_schema':{'name':'grounded_draft','strict':True,'schema':SCHEMA}}}
            if self.name=='deepseek':
                payload['response_format']={'type':'json_object'}
                payload['thinking']={'type':'enabled'}
                payload['reasoning_effort']='high'
                payload['messages'][0]['content']+= '\nReturn only a JSON object with exactly these keys: text (string), fact_ids (array of supplied ID strings), unknowns (array of strings). Example: {"text":"A concise grounded draft.","fact_ids":[],"unknowns":[]}'
            response=client.post(self.base_url+'/chat/completions',headers=headers,json=payload)
            response.raise_for_status();data=response.json();tokens=data.get('usage',{})
            choice=data['choices'][0]
            if choice.get('finish_reason')=='length':raise ValueError('The AI draft was truncated; no partial draft was accepted.')
            draft=json.loads(choice['message']['content'])
            if self.name=='deepseek' and (not isinstance(draft,dict) or set(draft)!=set(SCHEMA['required']) or not isinstance(draft['text'],str) or any(not isinstance(draft[k],list) or any(not isinstance(v,str) for v in draft[k]) for k in ('fact_ids','unknowns'))):
                raise ValueError('Invalid grounded draft schema.')
            return draft,tokens.get('prompt_tokens'),tokens.get('completion_tokens')

def get_provider(strong=True):
    name=os.getenv('AI_PROVIDER','openai').lower();tier='STRONG' if strong else 'CHEAP'
    model=os.getenv('AI_'+tier+'_MODEL','deepseek-flash' if name=='deepseek' else 'gpt-6.1-sol' if strong else 'gpt-6-luna')
    if name=='openai':
        key=os.getenv('OPENAI_API_KEY','');base='https://api.openai.com/v1'
        if not key:raise HTTPException(409,'Optional AI is not connected. Add your own provider key in the server environment.')
    elif name=='deepseek':
        key=os.getenv('AI_API_KEY','') or os.getenv('DEEPSEEK_API_KEY','');base='https://api.deepseek.com'
        if not key:raise HTTPException(409,'DeepSeek is not connected. Add its key to the private server environment.')
        if model not in DEEPSEEK_RATES:raise HTTPException(409,'The native DeepSeek connector is configured for deepseek-flash.')
    elif name in ('compatible','local'):
        key=os.getenv('AI_API_KEY','');base=os.getenv('AI_BASE_URL','').rstrip('/');target=urlparse(base)
        if name=='local' and target.hostname not in ('localhost','127.0.0.1','::1'):raise HTTPException(409,'Local inference must use a loopback endpoint.')
        if name=='compatible' and (target.scheme!='https' or not key):raise HTTPException(409,'A compatible paid provider requires HTTPS and its own key.')
        if target.scheme not in ('http','https'):raise HTTPException(409,'Configure AI_BASE_URL for the compatible server.')
    else:raise HTTPException(409,'AI_PROVIDER must be openai, deepseek, compatible or local.')
    if name=='local':rates=(0.,0.)
    elif name=='openai' and model in KNOWN_RATES:rates=KNOWN_RATES[model]
    elif name=='deepseek':rates=DEEPSEEK_RATES[model]
    else:
        try:rates=tuple(float(os.environ['AI_'+tier+'_'+k+'_USD_PER_MILLION']) for k in ('INPUT','OUTPUT'))
        except (KeyError,ValueError):raise HTTPException(409,'Declare input/output prices before enabling this paid model.')
        if min(rates)<=0:raise HTTPException(409,'Paid prices must be positive; use local for free loopback inference.')
    return Provider(name,model,key,base,rates,8192 if name=='deepseek' else 2200)

def provider_configured():
    try:get_provider();return True
    except HTTPException:return False
