import { Search, Code2, ShieldCheck, ScanLine, Database } from 'lucide-react';
import type { Translator } from '../i18n';
const icons=[Search,Code2,ShieldCheck,ScanLine];
export const stages=['explorer','coder','guardian','critic'] as const;
export function Pipeline({t,active=-1,rejected=-1,onSelect,selected}:{t:Translator;active?:number;rejected?:number;onSelect?:(index:number)=>void;selected?:number}){
  return <div className="pipeline" dir="ltr"><svg className="pipeline-lines" viewBox="0 0 560 84" preserveAspectRatio="none" aria-hidden="true"><path d="M65 42 H495"/><path className="pipeline-pulse" d="M65 42 H495"/></svg>
    {stages.map((stage,index)=>{const Icon=icons[index];return <button key={stage} className={`pipeline-node ${active>=index?'node-active':''} ${rejected===index?'node-rejected':''} ${selected===index?'node-selected':''}`} onClick={()=>onSelect?.(index)} disabled={!onSelect} aria-label={t(stage)} aria-pressed={onSelect?selected===index:undefined}><span className="node-icon"><Icon size={21} strokeWidth={1.5}/></span><span>{t(stage)}</span><small>0{index+1}</small></button>;})}
    <span className="database-node"><Database size={18}/></span>
  </div>;
}
