import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {JSDOM} from 'jsdom';
const content=readFileSync(new URL('../content.js',import.meta.url),'utf8');
function page(html,url='https://jobs.lever.co/fixture/job-1234'){
 const dom=new JSDOM(html,{url,runScripts:'outside-only'});
 dom.window.HTMLElement.prototype.getClientRects=()=>[{width:10,height:10}];
 dom.window.CSS={escape:v=>String(v).replaceAll('"','\\"')};
 dom.window.eval(content);return dom;
}
function pack(extra={}){return {application:{id:'test-only'},opportunity:{apply_url:'https://jobs.lever.co/fixture/job-1234'},fields:{display_name:'Test-only Applicant',email:'test@example.test'},resume_version:{id:'test-only-version',status:'approved'},auto_apply:{enabled:false,providers:[]},...extra};}
async function fill(dom,args){try{return await dom.window.__internshipOS.perform('fill',{pack:pack(),localFacts:{},...args});}finally{dom.window.close();}}

test('known factual fields fill, existing input survives, and legal answers remain unresolved',async()=>{
 const dom=page('<label for="name">Full name</label><input id="name" required><label for="email">Email</label><input id="email" value="existing@example.test"><label for="legal">Work authorization</label><select id="legal" required><option value="">Choose</option><option>Yes</option></select>');
 const result=await dom.window.__internshipOS.perform('fill',{pack:pack(),localFacts:{}});
 assert.equal(dom.window.document.querySelector('#name').value,'Test-only Applicant');
 assert.equal(dom.window.document.querySelector('#email').value,'existing@example.test');
 assert.ok(result.unresolved.some(x=>x.includes('Work authorization')));assert.equal(result.submitted,false);dom.window.close();
});
test('submission needs both workspace authorization and a per-application gesture',async()=>{
 const dom=page('<form><label for="name">Full name</label><input id="name" required><button type="submit">Submit application</button></form>');let submitted=0;dom.window.document.querySelector('form').addEventListener('submit',e=>{e.preventDefault();submitted++;});
 const result=await fill(dom,{submitConsent:true});assert.equal(submitted,0);assert.equal(result.submitted,false);assert.match(result.message,/not authorized/);
});
test('an opt-in for another provider cannot authorize submission',async()=>{
 const dom=page('<input aria-label="Full name"><form><button type="submit">Submit application</button></form>');
 const result=await fill(dom,{submitConsent:true,pack:pack({auto_apply:{enabled:true,providers:['greenhouse']}})});assert.equal(result.submitted,false);
});
test('a different job on the same employer board stops automatic submission',async()=>{
 const dom=page('<input aria-label="Full name"><form><button type="submit">Submit application</button></form>','https://jobs.lever.co/fixture/other-job');
 const result=await fill(dom,{submitConsent:true,pack:pack({auto_apply:{enabled:true,providers:['lever']}})});assert.equal(result.submitted,false);assert.match(result.message,/matched exactly/);
});
test('CAPTCHA and unknown mandatory answers stop supported auto-apply',async()=>{
 for(const html of ['<iframe src="https://hcaptcha.com/widget"></iframe>','<label for="question">Unknown mandatory question</label><input id="question" required>']){
  const dom=page('<input aria-label="Full name"><form>'+html+'<button type="submit">Submit application</button></form>');
  const result=await fill(dom,{submitConsent:true,pack:pack({auto_apply:{enabled:true,providers:['lever']}})});assert.equal(result.submitted,false);assert.match(result.message,/CAPTCHA|required|ambiguous/i);
 }
});
test('supported complete fixture submits only after explicit opt-in and preserves receipt evidence',async()=>{
 const dom=page('<form><label for="name">Full name</label><input id="name" required><button type="submit">Submit application</button></form>');let submitted=0;
 dom.window.document.querySelector('form').addEventListener('submit',e=>{e.preventDefault();submitted++;const receipt=dom.window.document.createElement('h1');receipt.textContent='Application received';dom.window.document.body.append(receipt);});
 const result=await fill(dom,{submitConsent:true,pack:pack({auto_apply:{enabled:true,providers:['lever']}})});
 assert.equal(submitted,1);assert.equal(result.submitted,true);assert.equal(result.receipt.evidence,'Application received');
});
test('plain page text saying fields were filled is never a receipt',()=>{
 const dom=page('<main>Form filled successfully. Click submit when ready.</main>');assert.equal(dom.window.__internshipOS.perform('receipt',{}),null);dom.window.close();
});
test('capture uses source JSON-LD facts without inventing an employer',()=>{
 const dom=page('<script type="application/ld+json">{"@type":"JobPosting","title":"Test-only Backend Intern","hiringOrganization":{"name":"Fixture Labs"},"description":"Build &lt;b&gt;Python&lt;/b&gt; services","jobLocation":{"address":{"addressLocality":"Bengaluru"}}}</script>');
 const captured=dom.window.__internshipOS.perform('capture',{});assert.equal(captured.company_name,'Fixture Labs');assert.equal(captured.title,'Test-only Backend Intern');assert.match(captured.description,/Python/);assert.equal(captured.location,'Bengaluru');dom.window.close();
});


test('server packs cannot submit without a reserved lease',async()=>{
 const dom=page('<form><input aria-label="Full name" required><button type="submit">Submit application</button></form>');
 const result=await fill(dom,{submitConsent:true,pack:pack({requires_submission_lease:true,auto_apply:{enabled:true,providers:['lever']}})});
 assert.equal(result.submitted,false);assert.match(result.message,/reserve a submission/);
});

test('approved batches stop on conflicting prefilled facts rather than submitting them',async()=>{
 const dom=page('<form><input aria-label="Email" value="other@example.test" required><button type="submit">Submit application</button></form>');
 const result=await fill(dom,{requireExactFacts:true,submitConsent:false});
 assert.equal(result.submitted,false);assert.match(result.unresolved[0],/existing answer/);
});
for(const [name,url] of [['greenhouse','https://job-boards.greenhouse.io/fixture/jobs/job-1234'],['ashby','https://jobs.ashbyhq.com/fixture/job-1234']]){
 test(name+' fixture preserves approved job binding and receipt',async()=>{
  const dom=page('<form><input aria-label="Full name" required><button type="submit">Submit application</button></form>',url);
  dom.window.document.querySelector('form').addEventListener('submit',e=>{e.preventDefault();const receipt=dom.window.document.createElement('h1');receipt.textContent='Application received';dom.window.document.body.append(receipt);});
  const result=await fill(dom,{submitConsent:true,submissionLease:{lease:'fixture-only',application_id:'test-only',resume_version_id:'test-only-version',expires_at:new Date(Date.now()+60000).toISOString()},pack:pack({opportunity:{apply_url:url},requires_submission_lease:true,auto_apply:{enabled:true,providers:[name]}})});
  assert.equal(result.submitted,true);assert.ok(result.receipt);
 });
}
