import { useMemo, useState } from 'react';
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip } from 'recharts';
import { ChartNoAxesCombined } from 'lucide-react';
import type { Translator } from '../i18n';
export default function ChartPanel({columns,rows,t}:{columns:string[];rows:unknown[][];t:Translator}){
  const metrics=columns.map((name,index)=>({name,index})).filter(({index})=>rows.some(row=>row[index]!==null&&row[index]!==''&&Number.isFinite(Number(row[index]))));
  const [selected,setSelected]=useState('');const metric=metrics.find(item=>item.name===selected)??metrics[metrics.length-1];
  const dimension=columns.findIndex((_,index)=>index!==metric?.index&&rows.some(row=>typeof row[index]==='string'&&!Number.isFinite(Number(row[index]))));
  const data=useMemo(()=>rows.slice(0,30).map((row,index)=>({name:dimension>=0?String(row[dimension]):String(index+1),value:metric?Number(row[metric.index]):0})),[rows,dimension,metric?.index]);
  return <div className="chart-panel"><div className="panel-header"><h3><ChartNoAxesCombined size={15}/>{t('analytics')}</h3>{metric&&<select aria-label={t('metric')} value={metric.name} onChange={event=>setSelected(event.target.value)}>{metrics.map(item=><option key={item.name}>{item.name}</option>)}</select>}</div><div className="chart-body" dir="ltr">{metric&&rows.length?<ResponsiveContainer width="100%" height={230}><BarChart data={data} margin={{left:4,right:20,top:15,bottom:8}}><CartesianGrid vertical={false} stroke="#253046" strokeDasharray="3 4"/><XAxis dataKey="name" stroke="#8492a8" tickLine={false} axisLine={false} fontSize={11}/><YAxis stroke="#8492a8" tickLine={false} axisLine={false} fontSize={11} width={58}/><Tooltip cursor={{fill:'#ffffff06'}} contentStyle={{background:'#101826',border:'1px solid #334155',borderRadius:6,color:'#e2e8f0'}}/><Bar dataKey="value" fill="#57c3ec" radius={[3,3,0,0]} maxBarSize={48}/></BarChart></ResponsiveContainer>:<div className="empty-chart"><ChartNoAxesCombined size={25}/>{t('chartUnavailable')}</div>}</div><p className="chart-note">{t('chartNote')}</p></div>;
}
