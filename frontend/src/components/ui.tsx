import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { ShieldCheck, ArrowUpRight, Languages, Check, Copy } from 'lucide-react';
import { useState } from 'react';
import type { Language, Translator } from '../i18n';
export function Button({children,className='',variant='primary',...props}:ButtonHTMLAttributes<HTMLButtonElement>&{variant?:'primary'|'secondary'|'ghost'}){return <button {...props} className={`button button-${variant} ${className}`}>{children}</button>;}
export function Brand({compact=false}:{compact?:boolean}){return <a href="#" className="brand" aria-label="SentinelSQL home"><span className="brand-mark"><ShieldCheck size={22} strokeWidth={1.6}/></span><span>Sentinel<span className="brand-light">SQL</span>{!compact&&<small>THE DETERMINISTIC SQL GATEWAY</small>}</span></a>;}
export function LanguageButton({language,onChange}:{language:Language;onChange:()=>void}){return <button className="language-button" onClick={onChange} aria-label={language==='en'?'Switch to Arabic':'Switch to English'}><Languages size={16}/>{language==='en'?'العربية':'English'}</button>;}
export function SectionLabel({children}:{children:ReactNode}){return <div className="section-label"><span/>{children}</div>;}
export function CopyButton({text,t}:{text:string;t:Translator}){const [copied,setCopied]=useState(false);return <Button variant="ghost" disabled={!text} onClick={()=>void navigator.clipboard.writeText(text).then(()=>{setCopied(true);setTimeout(()=>setCopied(false),1500);})}>{copied?<Check size={14}/>:<Copy size={14}/>} {t(copied?'copied':'copy')}</Button>;}
export function Arrow(){return <ArrowUpRight className="directional" size={16}/>;}
export function SQLCode({sql,diff=false}:{sql:string;diff?:boolean}){
  if(diff)return <pre dir="ltr" className="sql-code">{sql.split('\n').map((line,index)=><div key={index} className={line.startsWith('+')?'diff-add':line.startsWith('-')?'diff-remove':''}>{line||' '}</div>)}</pre>;
  return <pre dir="ltr" className="sql-code">{sql.split(/('(?:[^']|'')*'|\b(?:WITH|AS|SELECT|TOP|FROM|JOIN|INNER|WHERE|GROUP|BY|ORDER|DESC|SUM|ROUND|COUNT|ON|AND|INSERT|DELETE|DROP)\b|\b\d+(?:\.\d+)?\b)/gi).map((token,index)=><span key={index} className={token.startsWith("'")?'sql-string':/^[A-Z]+$/i.test(token.trim())?'sql-keyword':/^\d/.test(token)?'sql-number':''}>{token}</span>)}</pre>;
}
