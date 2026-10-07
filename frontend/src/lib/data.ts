export function compareCells(a:unknown,b:unknown):number {
  const left=String(a??''),right=String(b??'');
  const decimal=/^-?\d+(?:\.\d+)?$/;
  if(decimal.test(left)&&decimal.test(right)){
    const scale=Math.max(left.split('.')[1]?.length??0,right.split('.')[1]?.length??0);
    const integer=(value:string)=>{const negative=value.startsWith('-');const [whole,fraction='']=value.replace(/^-/,'').split('.');return BigInt(whole+fraction.padEnd(scale,'0'))*(negative?-1n:1n);};
    const x=integer(left),y=integer(right);return x<y?-1:x>y?1:0;
  }
  return left.localeCompare(right,undefined,{numeric:true});
}
export function csv(columns:string[],rows:unknown[][]){
  const cell=(value:unknown)=>{let string=String(value??'');if(typeof value==='string'&&/^[\s]*[=+\-@\t\r]/.test(string))string="'"+string;return '"'+string.replaceAll('"','""')+'"';};
  return '\uFEFF'+[columns,...rows].map(row=>row.map(cell).join(',')).join('\r\n');
}
export function download(value:Blob,filename:string){const url=URL.createObjectURL(value);const anchor=document.createElement('a');anchor.href=url;anchor.download=filename;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
export function workbookParts(columns:string[],rows:unknown[][]):Record<string,string>{
  const escape=(value:unknown)=>String(value??'').replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g,'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
  const letter=(index:number)=>{let text='';for(let n=index+1;n;n=Math.floor((n-1)/26))text=String.fromCharCode(65+(n-1)%26)+text;return text;};
  const records=[columns,...rows].map((row,index)=>`<row r="${index+1}">${row.map((value,column)=>{
    const cell=`r="${letter(column)}${index+1}"${index===0?' s="1"':''}`;
    if(index>0&&typeof value==='number'&&Number.isFinite(value))return `<c ${cell}><v>${value}</v></c>`;
    if(index>0&&typeof value==='boolean')return `<c ${cell} t="b"><v>${value?1:0}</v></c>`;
    return `<c ${cell} t="inlineStr"><is><t xml:space="preserve">${escape(value)}</t></is></c>`;
  }).join('')}</row>`).join('');
  return {
    '[Content_Types].xml':'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>',
    '_rels/.rels':'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
    'xl/workbook.xml':'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Query results" sheetId="1" r:id="rId1"/></sheets></workbook>',
    'xl/_rels/workbook.xml.rels':'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
    'xl/styles.xml':'<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF172033"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>',
    'xl/worksheets/sheet1.xml':`<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols><col min="1" max="${Math.max(1,columns.length)}" width="24" customWidth="1"/></cols><sheetData>${records}</sheetData></worksheet>`,
  };
}
export async function excel(columns:string[],rows:unknown[][]){const {zipSync,strToU8}=await import('fflate');const parts=workbookParts(columns,rows);const archive=zipSync(Object.fromEntries(Object.entries(parts).map(([name,xml])=>[name,strToU8('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'+xml)])));download(new Blob([archive.buffer as ArrayBuffer],{type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}),'sentinel-results.xlsx');}
