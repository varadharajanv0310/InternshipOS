export type SearchFilters = Record<string,string>;
export type SavedSearchView = {id:string;name:string;filters:SearchFilters};
export const extraFilterKeys=['work_mode','eligibility','source','risk','fresh_days','application_stage','pay','min_worth'] as const;
export const savedViewsKey='ios:opportunity-views:v1';
const allowedKeys=['q','role','location','kind','saved','min_fit','sort',...extraFilterKeys];
export function normalizeSearchFilters(value:unknown):SearchFilters {
  if(!value||typeof value!=='object')return {};
  return Object.fromEntries(allowedKeys.map(key=>[key,String((value as SearchFilters)[key]??'').slice(0,500)]));
}
export function parseSavedViews(raw:string|null):SavedSearchView[] {
  try {const data=JSON.parse(raw||'[]');if(!Array.isArray(data))return [];return data.filter(v=>v&&typeof v.id==='string'&&typeof v.name==='string'&&v.filters&&typeof v.filters==='object').slice(0,30).map(v=>({id:v.id,name:v.name.slice(0,80),filters:normalizeSearchFilters(v.filters)}));}catch{return [];}
}
export function opportunityQuery(filters:SearchFilters,page=1) {
  const values=normalizeSearchFilters(filters);
  return new URLSearchParams({...Object.fromEntries(Object.entries(values).filter(([,v])=>v!=='')),technical:values.role==='all'||values.role==='Other'?'false':'true',page:String(page),page_size:'30'});
}
