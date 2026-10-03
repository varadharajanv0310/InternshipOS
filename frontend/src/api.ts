import { useCallback, useEffect, useState } from 'react';

export type Row = Record<string, any>;
export type Collection<T = Row> = { items: T[]; total: number; page?: number; facets?: Row };
export class APIError extends Error { constructor(message: string, public status: number) { super(message); } }
export async function api<T = Row>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  const multipart = body instanceof FormData;
  const response = await fetch(`/api${path}`, {method, credentials:'same-origin', signal, headers: body && !multipart ? {'Content-Type':'application/json'} : {}, body: multipart ? body : body ? JSON.stringify(body) : undefined});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event('ios:unauthorized'));
    const detail = data.detail;
    throw new APIError(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((x: Row) => `${(x.loc || []).slice(1).join('.')}: ${x.msg}`).join('; ') : data.message || `Request failed (${response.status}).`, response.status);
  }
  return data as T;
}
export function invalidate() { window.dispatchEvent(new Event('ios:refresh')); }
export function useResource<T = Row>(path: string | null) {
  const [data, setData] = useState<T | null>(null), [loading,setLoading]=useState(true), [error,setError]=useState(''), [revision,setRevision]=useState(0);
  const refresh=useCallback(()=>setRevision(v=>v+1),[]);
  useEffect(()=>{ window.addEventListener('ios:refresh',refresh); return ()=>window.removeEventListener('ios:refresh',refresh); },[refresh]);
  useEffect(()=>{
    if (!path) { setLoading(false); return; }
    const controller=new AbortController(); setLoading(true); setError('');
    api<T>(path,'GET',undefined,controller.signal).then(setData).catch(e=>{if(e.name!=='AbortError')setError(e.message);}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[path,revision]);
  return {data,loading,error,refresh};
}
export const items = (value: any): Row[] => Array.isArray(value) ? value : value?.items || [];
export const readable = (value: any): string => value == null ? 'Not specified' : String(value).replaceAll('_',' ').replace(/\b\w/g,x=>x.toUpperCase());
export const numeric = (value: any): number | null => value == null || value === '' || !Number.isFinite(Number(value)) ? null : Number(value);
export function date(value?: string, withTime=false) { if(!value)return 'Not specified'; const parsed=new Date(value); if(Number.isNaN(parsed.valueOf())) return value; return new Intl.DateTimeFormat(undefined,{month:'short',day:'numeric',...(withTime?{hour:'numeric',minute:'2-digit'}:{})}).format(parsed); }
export function relative(value?: string) { if(!value)return 'Not checked'; const hours=(Date.now()-new Date(value).valueOf())/3600000; if(!Number.isFinite(hours))return 'Not checked'; if(hours<1)return 'Just now'; if(hours<24)return `${Math.floor(hours)}h ago`; if(hours<48)return 'Yesterday'; return `${Math.floor(hours/24)}d ago`; }
export function safeUrl(value?: string) { try { const url=new URL(value || ''); return ['http:','https:'].includes(url.protocol) ? url.href : undefined; } catch {return undefined;} }
export function downloadUrl(id:string) { return `/api/resume-versions/${encodeURIComponent(id)}/download`; }
