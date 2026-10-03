import test from 'node:test';
import assert from 'node:assert/strict';
import {createQueueRunner} from '../background.js';

function fixture({unknown=false,receipt=true}={}){
 const storage={connection:{apiUrl:'https://workspace.example/api',token:'fixture-only'},facts:{fullName:'Test applicant'}},calls=[];
 let submitted=false,claims=0;
 const pack={application:{id:'a1'},resume_version:{id:'v1'},resume_download_url:'/api/resume-versions/v1/download',auto_apply:{enabled:true}};
 const browser={storage:{local:{get:async key=>({[key]:storage[key]}),set:async values=>Object.assign(storage,values)}},alarms:{create:async()=>{},clear:async()=>{}},tabs:{create:async()=>({id:42}),get:async()=>({status:'complete'})},scripting:{executeScript:async config=>config.files?[]:config.args[1]==='openApplication'?[{result:{navigated:false}}]:[{result:config.args[0].submitConsent?{receipt:receipt?{url:'https://jobs.lever.co/acme/job-id',evidence:'Application received'}:null}:{unresolved:unknown?['Work authorization']:[],challenge:false,form_present:true,job_matches:true,resume_uploaded:true}}]}};
 const fetcher=async(url,options={})=>{
  const path=new URL(url).pathname;calls.push(path);
  if(path.endsWith('/download'))return {ok:true,arrayBuffer:async()=>new Uint8Array([37,80,68,70]).buffer};
  let data;
  if(path.endsWith('/queue'))data={items:submitted?[]:[{id:'a1',state:'approved',approval_current:true,blockers:[],url:'https://jobs.lever.co/acme/job-id',company:'Fixture',title:'Software Intern'}]};
  else if(path.endsWith('/pack'))data=pack;
  else if(path.endsWith('/claim')){claims++;data={lease:'one-use',application_id:'a1',resume_version_id:'v1',expires_at:new Date(Date.now()+60000).toISOString()};}
  else if(path.endsWith('/receipt')){submitted=true;data={};}
  else data={};
  return {ok:true,json:async()=>data};
 };
 return {runner:createQueueRunner(browser,fetcher),storage,calls,get claims(){return claims;}};
}

test('approved browser queue reserves once and records confirmed receipt before continuing',async()=>{
 const f=fixture();await f.runner.start();assert.equal(f.claims,0);await f.runner.advance();assert.equal(f.claims,1);assert.ok(f.calls.includes('/api/extension/receipt'));assert.equal(f.storage.queueRunner.completed,1);await f.runner.advance();assert.equal(f.storage.queueRunner.active,false);assert.equal(f.claims,1);
});
test('unknown required fields pause before consuming a submission attempt',async()=>{
 const f=fixture({unknown:true});await f.runner.start();await f.runner.advance();assert.equal(f.claims,0);assert.equal(f.storage.queueRunner.active,false);assert.match(f.storage.queueRunner.reason,/review/);
});
test('missing receipt pauses without retrying or declaring submission',async()=>{
 const f=fixture({receipt:false});await f.runner.start();await f.runner.advance();await f.runner.advance();assert.equal(f.claims,1);assert.ok(f.calls.includes('/api/extension/attempt-stopped'));assert.equal(f.storage.queueRunner.active,false);assert.ok(!f.calls.includes('/api/extension/receipt'));
});
test('a restarted worker resolves an interrupted lease as uncertain and never resubmits',async()=>{
 const f=fixture();f.storage.queueRunner={active:true,pending:{id:'a1',phase:'attempting',lease:{lease:'previous'}}};await f.runner.recover();await f.runner.advance();assert.equal(f.claims,0);assert.equal(f.storage.queueRunner.active,false);assert.ok(f.calls.includes('/api/extension/attempt-stopped'));
});
