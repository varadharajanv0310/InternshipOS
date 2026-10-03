import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { mkdir, rm } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { join } from 'node:path';
const root=fileURLToPath(new URL('..',import.meta.url));
const folder=join(root,'.test-build');
await mkdir(folder,{recursive:true});
const output=join(folder,'harness.mjs');
await build({entryPoints:[join(root,'tests','harness.tsx')],outfile:output,bundle:true,format:'esm',platform:'node',packages:'external',jsx:'automatic',logLevel:'silent'});
const ui=await import(pathToFileURL(output).href);
test.after(async()=>{await rm(output,{force:true});});

test('PDF uploads send multipart data without overriding the browser boundary',async()=>{
 const previous=globalThis.fetch;let request;
 globalThis.fetch=async(url,options)=>{request={url,...options};return {ok:true,json:async()=>({id:'uploaded-version'})};};
 try {
  const body=new FormData();body.append('file',new Blob(['fixture'],{type:'application/pdf'}),'fixture.pdf');
  const result=await ui.api('/resumes/upload','POST',body);
  assert.equal(result.id,'uploaded-version');assert.equal(request.body,body);
  assert.equal(request.url,'/api/resumes/upload');assert.equal(request.credentials,'same-origin');
  assert.equal(request.headers['Content-Type'],undefined);
 } finally {globalThis.fetch=previous;}
});

test('existing profile writes continue sending JSON',async()=>{
 const previous=globalThis.fetch;let request;
 globalThis.fetch=async(url,options)=>{request=options;return {ok:true,json:async()=>({saved:true})};};
 try {await ui.api('/profile','PATCH',{display_name:'Test-only'});assert.equal(request.headers['Content-Type'],'application/json');assert.equal(JSON.parse(request.body).display_name,'Test-only');}
 finally {globalThis.fetch=previous;}
});

test('dashboard opportunity cards include the actual role, employer, location and accessible save action',()=>{
 const html=ui.renderCard({id:'fixture-only',title:'Backend intern',company:{name:'Example employer'},location:'Bengaluru, India',opportunity_type:'internship',eligibility:'eligible',fit_score:null,worth_score:0,saved:false});
 for(const text of ['Backend intern','Example employer','Bengaluru, India','Eligible','Save opportunity'])assert.ok(html.includes(text),`Missing ${text}`);
 assert.match(html,/class="badge green"/);
 assert.doesNotMatch(html,/>undefined</);
});
test('source text cannot insert executable markup into a card',()=>{
 const html=ui.renderCard({id:'fixture-only',title:'<img src=x onerror=alert(1)>',company:{name:'<script>bad()</script>'}});
 assert.ok(html.includes('&lt;img'));
 assert.ok(html.includes('&lt;script&gt;'));
 assert.ok(!html.includes('<script>'));
});
test('an unknown score is distinct from a real zero',()=>{
 assert.equal(ui.numeric(null),null);assert.equal(ui.numeric(''),null);assert.equal(ui.numeric(0),0);
 assert.ok(ui.renderScore(null).includes('not evaluated'));
 assert.ok(ui.renderScore(0).includes('>0</span>'));
});
test('only ordinary web addresses become outgoing links',()=>{
 assert.equal(ui.safeUrl('javascript:alert(1)'),undefined);
 assert.equal(ui.safeUrl('data:text/html,test'),undefined);
 assert.equal(ui.safeUrl('https://example.com/job'), 'https://example.com/job');
});
test('backend chart dimensions retain counts, range labels and zero observations',()=>{
 assert.deepEqual(ui.chartSeries([{range:'0–20',count:0},{date:'2026-10-02',count:3}]).map(({name,value})=>({name,value})),[{name:'0–20',value:0},{name:'2026-10-02',value:3}]);
 assert.deepEqual(ui.chartSeries({}),[]);
});
test('health charts use actual run counts instead of treating an object as an empty collection',()=>{
 assert.deepEqual(ui.healthSeries({complete_runs:3,total_runs:8,failures:4}).map(x=>x.count),[3,4,1]);
});
test('compensation visibility does not combine currencies, infer unpaid work or invent observations',()=>{
 const pay=[{min:1000,currency:'INR',period:'month'},{min:15,currency:'USD',period:'hour'}];
 assert.deepEqual(ui.compensationVisibility(pay,5),[{name:'Numeric pay disclosed',count:2},{name:'Numeric pay not available',count:3}]);
 assert.deepEqual(ui.compensationVisibility([],0),[]);
});
test('activity displays the event title and useful collection evidence',()=>{
 assert.equal(ui.activityTitle({title:'Company source refreshed',entity_type:'source'}),'Company source refreshed');
 assert.match(ui.activityDetail({data:{accepted_unique:12,created:4,updated:2,can_infer_absence:false}}),/12 observations.*4 new.*Closure inference withheld/);
});
test('eligibility states normalize API casing without treating an unknown as a pass',()=>{
 assert.equal(ui.eligibilityLabel('eligible'),'Eligible');assert.equal(ui.eligibilityTone('Ineligible'),'red');
 assert.equal(ui.eligibilityLabel(undefined),'Unclear');assert.equal(ui.eligibilityTone('unknown'),'amber');
});
test('advanced filters retain exact API names and the default technical scope',()=>{
 const params=ui.opportunityQuery({q:'a&source=untrusted',role:'',kind:'internship',location:'India',work_mode:'remote',eligibility:'eligible',source:'lever',risk:'verified',fresh_days:'7',application_stage:'none',pay:'known',min_worth:'70'},2);
 assert.equal(params.get('technical'),'true');assert.equal(params.get('q'),'a&source=untrusted');assert.equal(params.get('source'),'lever');assert.equal(params.get('min_worth'),'70');assert.equal(params.get('page'),'2');assert.equal(params.get('application_stage'),'none');
 assert.equal(ui.opportunityQuery({role:'all'}).get('technical'),'false');
});
test('named saved views round-trip filters while rejecting malformed browser storage',()=>{
 const view={id:'test-view',name:'Remote shortlist',filters:{work_mode:'remote',saved:'true',min_worth:'70',unsupported:'discard'}};
 const [restored]=ui.parseSavedViews(JSON.stringify([view]));
 assert.equal(restored.name,'Remote shortlist');assert.equal(restored.filters.work_mode,'remote');assert.equal(restored.filters.saved,'true');assert.equal(restored.filters.unsupported,undefined);
 assert.deepEqual(ui.parseSavedViews('{broken'),[]);assert.deepEqual(ui.parseSavedViews('{}'),[]);
});
