/// <reference types="vite/client" />
import { useEffect, useRef, useState } from 'react';
import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist/legacy/build/pdf.mjs';
import workerUrl from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?url';
import { downloadUrl } from './api';

GlobalWorkerOptions.workerSrc = workerUrl;

export default function PDFPreview({id}:{id:string}) {
  const container = useRef<HTMLDivElement>(null);
  const [error,setError] = useState(''), [loading,setLoading] = useState(true);
  useEffect(()=>{
    let stopped=false;
    const target=container.current;
    target?.replaceChildren();setLoading(true);setError('');
    const task=getDocument({url:downloadUrl(id),withCredentials:true});
    task.promise.then(async pdf=>{
      for(let number=1;number<=pdf.numPages;number++) {
        if(stopped||!target)return;
        const page=await pdf.getPage(number);
        const viewport=page.getViewport({scale:1.5});
        const canvas=document.createElement('canvas');
        canvas.width=Math.ceil(viewport.width);canvas.height=Math.ceil(viewport.height);
        canvas.style.cssText='display:block;width:100%;height:auto;margin:0 auto 16px;background:white';
        canvas.setAttribute('role','img');canvas.setAttribute('aria-label',`Resume PDF page ${number}`);
        const context=canvas.getContext('2d');if(!context)throw new Error('Canvas unavailable');
        await page.render({canvas,canvasContext:context,viewport}).promise;
        if(stopped)return;
        target.appendChild(canvas);
      }
      if(!stopped)setLoading(false);
    }).catch(()=>{if(!stopped){setError('The preview could not load. Download the original PDF to review it.');setLoading(false);}});
    return ()=>{stopped=true;void task.destroy();};
  },[id]);
  return <div>{loading&&<p role="status">Loading your PDF…</p>}{error&&<p role="alert">{error}</p>}<div ref={container} aria-label="Original resume PDF" style={{maxHeight:'70vh',overflow:'auto',padding:12,background:'#e8eaf0',borderRadius:8}}/></div>;
}
