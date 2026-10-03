/* Processes only explicitly approved packs after the owner starts a browser batch. */
export function createQueueRunner(browser, fetcher=fetch) {
  let running=false;
  const alarm='internshipos-approved-queue';
  async function read(){return (await browser.storage.local.get('queueRunner')).queueRunner||{active:false,pending:null};}
  async function save(state){await browser.storage.local.set({queueRunner:state});}
  async function request(path,method='GET',body){
    const {connection}=await browser.storage.local.get('connection');
    if(!connection?.token)throw Error('Reconnect your workspace.');
    const response=await fetcher(connection.apiUrl.replace(/\/$/,'')+path,{method,headers:{Authorization:'Bearer '+connection.token,'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});
    const data=await response.json();if(!response.ok)throw Error(data.detail||'Workspace request failed.');return data;
  }
  async function pause(reason){const state=await read();await save({...state,active:false,reason});await browser.alarms.clear(alarm);}
  async function uncertain(pending,reason){
    if(pending?.lease){try{await request('/extension/attempt-stopped','POST',{application_id:pending.id,lease:pending.lease.lease});}catch{/* Persist the lease locally even if the network is unavailable. */}}
    await pause(reason);
  }
  async function inject(tabId,args,action='fill'){
    await browser.scripting.executeScript({target:{tabId},files:['content.js']});
    const [result]=await browser.scripting.executeScript({target:{tabId},func:(args,action)=>window.__internshipOS.perform(action,args),args:[args,action]});
    return result.result;
  }
  async function resumeFile(pack){
    if(!pack.resume_download_url)throw Error('An approved resume PDF is required.');
    const {connection}=await browser.storage.local.get('connection');
    const url=new URL(pack.resume_download_url,new URL(connection.apiUrl).origin);
    if(url.origin!==new URL(connection.apiUrl).origin)throw Error('Resume download origin changed.');
    const response=await fetcher(url.href,{headers:{Authorization:'Bearer '+connection.token}});
    if(!response.ok)throw Error('Resume PDF is unavailable.');
    const bytes=new Uint8Array(await response.arrayBuffer());
    return {base64:btoa(Array.from(bytes,b=>String.fromCharCode(b)).join('')),name:'resume-'+pack.resume_version.id.slice(0,8)+'.pdf'};
  }
  async function advance(){
    if(running)return;running=true;
    try{
      let state=await read();if(!state.active)return;
      if(state.pending?.phase==='attempting'){
        await uncertain(state.pending,'An interrupted attempt needs a receipt check. It will not be retried.');return;
      }
      if(!state.pending){
        const queue=await request('/extension/queue');
        const next=queue.items.find(a=>a.state==='approved'&&a.approval_current&&!a.blockers.length);
        if(!next){await pause('No current, approved applications remain.');return;}
        const url=new URL(next.url);
        if(url.protocol!=='https:'||!/(^|\.)(greenhouse\.io|lever\.co|ashbyhq\.com)$/.test(url.hostname))throw Error('This application needs manual review on an unsupported provider.');
        const pack=await request('/extension/pack?application_id='+encodeURIComponent(next.id));
        if(!pack.auto_apply?.enabled)throw Error('Enable supported browser submission in workspace Settings first.');
        const tab=await browser.tabs.create({url:url.href,active:false});
        await save({...state,pending:{id:next.id,tabId:tab.id,phase:'preparing',opened_at:Date.now()},reason:'Preparing '+next.company+' · '+next.title});
        return;
      }
      const pending=state.pending,tab=await browser.tabs.get(pending.tabId);
      if(tab.status!=='complete'){
        if(Date.now()-pending.opened_at>120000)throw Error('The application page did not finish loading.');
        return;
      }
      const pack=await request('/extension/pack?application_id='+encodeURIComponent(pending.id));
      const opened=await inject(pending.tabId,{pack},'openApplication');
      if(opened.navigated){await save({...state,pending:{...pending,opened_at:Date.now()}});return;}
      const file=await resumeFile(pack);
      const prepared=await inject(pending.tabId,{pack,localFacts:state.facts,file,requireExactFacts:true,submitConsent:false});
      if(prepared.unresolved.length||prepared.challenge||!prepared.form_present||!prepared.job_matches||!prepared.resume_uploaded)throw Error('This form needs review: required answers, a challenge, navigation or an unsupported form.');
      if(!(await read()).active)return;
      const lease=await request('/extension/claim','POST',{application_id:pending.id});
      pending.lease=lease;pending.phase='attempting';
      await browser.storage.local.set({activeApplicationId:pending.id,submissionLease:lease,activeResumeVersionId:pack.resume_version.id});
      state=await read();await save({...state,pending});
      if(!state.active){await uncertain(pending,'Batch stopped after reservation. Review this attempt before restarting.');return;}
      const result=await inject(pending.tabId,{pack,localFacts:state.facts,file,requireExactFacts:true,submitConsent:true,submissionLease:lease});
      if(!result.receipt){await uncertain(pending,'No confirmed receipt. Check this application before another attempt.');return;}
      await request('/extension/receipt','POST',{application_id:pending.id,resume_version_id:pack.resume_version.id,lease:lease.lease,...result.receipt});
      state=await read();await save({...state,pending:null,completed:(state.completed||0)+1,reason:'Confirmed submission receipt saved.'});
    }catch(error){const state=await read();if(state.pending?.lease)await uncertain(state.pending,error.message);else await pause(error.message);}
    finally{running=false;}
  }
  async function start(){
    const state=await read();if(state.active)throw Error('An approved queue is already running.');
    if(state.pending?.lease){
      const queue=await request('/extension/queue');
      if(queue.items.find(a=>a.id===state.pending.id)?.state!=='submitted')throw Error('Resolve the previous attempt and its receipt before starting a new batch.');
    }
    const {facts={}}=await browser.storage.local.get('facts');
    await save({active:true,pending:null,completed:0,facts,reason:'Approved queue started.'});
    await browser.alarms.create(alarm,{delayInMinutes:1,periodInMinutes:1});await advance();
  }
  async function recover(){
    const state=await read();
    if(state.active){if(state.pending?.phase==='attempting')await uncertain(state.pending,'Browser restarted during an attempt. Check its receipt.');else await browser.alarms.create(alarm,{delayInMinutes:1,periodInMinutes:1});}
  }
  return {start,advance,pause,read,recover};
}

if(typeof chrome!=='undefined'){
  const runner=createQueueRunner(chrome);
  chrome.runtime.onMessage.addListener((message,sender,reply)=>{
    if(!['startApprovedQueue','stopApprovedQueue'].includes(message.action))return;
    const action=message.action==='startApprovedQueue'?runner.start():runner.pause('Paused by you. Check any current attempt before restarting.');
    action.then(()=>runner.read()).then(reply).catch(error=>reply({error:error.message}));return true;
  });
  chrome.alarms.onAlarm.addListener(alarm=>{if(alarm.name==='internshipos-approved-queue')runner.advance();});
  chrome.tabs.onUpdated.addListener((tabId,change)=>{if(change.status==='complete')runner.advance();});
  chrome.runtime.onStartup.addListener(()=>runner.recover());
}
