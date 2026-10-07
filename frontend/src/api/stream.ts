import { api, websocketURL, type Job, type Trace } from './client';
type Callbacks={event:(event:Trace)=>void;rows:(offset:number,columns:string[],rows:unknown[][])=>void;result:(job:Job)=>void;state:(state:string)=>void;error:(message:string,code?:string)=>void;job:(id:string)=>void};
export class QueryStream {
  private socket?:WebSocket;private stopped=false;private started=false;private acknowledged=false;private id?:string;
  private cursor=0;private attempts=0;private timer?:ReturnType<typeof setTimeout>;private queue:unknown[]=[];private draining=false;
  private pending=new Map<number,Trace>();private recovering=false;private finalResult?:Job;
  constructor(private token:string,private question:string,private callback:Callbacks,private factory=(url:string)=>new WebSocket(url)){}
  connect(){
    if(this.stopped)return;
    this.callback.state(this.attempts?'reconnecting':'connecting');
    const socket=this.socket=this.factory(websocketURL());
    this.timer=setTimeout(()=>socket.close(1000,'Handshake deadline'),5000);
    socket.onopen=()=>this.send({token:this.token});
    socket.onmessage=event=>{
      if(typeof event.data!=='string'||event.data.length>3*1024*1024){this.fail('Invalid stream payload.');return;}
      try{this.queue.push(JSON.parse(event.data));}catch{this.fail('Invalid stream payload.');return;}
      if(this.queue.length>512){this.fail('Stream receive budget exceeded.');return;}
      if(!this.draining){this.draining=true;queueMicrotask(()=>this.drain());}
    };
    socket.onclose=()=>{
      clearTimeout(this.timer);if(this.stopped)return;
      if(this.started&&!this.acknowledged){this.fail('Connection lost before job acknowledgement. The query was not resubmitted.');return;}
      if(++this.attempts>5){this.fail('Connection interrupted. Reconnect or inspect the owned job.');return;}
      this.timer=setTimeout(()=>this.connect(),Math.min(8000,400*2**this.attempts));
      this.callback.state('reconnecting');
    };
    socket.onerror=()=>this.callback.state('reconnecting');
  }
  private send(frame:unknown){
    if(this.socket?.readyState!==1)return;
    if(this.socket.bufferedAmount>65536){this.fail('Stream send budget exceeded.');return;}
    this.socket.send(JSON.stringify(frame));
  }
  private drain(){
    let processed=0;
    while(this.queue.length&&processed++<32){this.consume(this.queue.shift());}
    if(this.queue.length)setTimeout(()=>this.drain(),0);else this.draining=false;
  }
  private consume(value:unknown){
    if(this.stopped||!value||typeof value!=='object')return;
    const frame=value as Record<string,unknown>;
    if(frame.type==='ready'){
      clearTimeout(this.timer);this.callback.state('connected');
      if(this.id)this.send({action:'subscribe',job_id:this.id,after_sequence:this.cursor});
      else if(!this.started){this.started=true;this.send({action:'start',question:this.question});}
    }else if(frame.type==='job'&&typeof frame.job_id==='string'){
      this.id=frame.job_id;this.acknowledged=true;this.callback.job(this.id);
    }else if(frame.type==='event'&&typeof frame.sequence==='number'&&typeof frame.agent==='string'){
      const event=frame as unknown as Trace;
      if(event.sequence<=this.cursor)return;
      this.pending.set(event.sequence,event);this.flush();
      if(this.pending.size>256){this.fail('Event replay budget exceeded.');return;}
      if(this.pending.size&&!this.recovering)void this.recover();
    }else if(frame.type==='rows'&&typeof frame.offset==='number'&&Array.isArray(frame.columns)&&Array.isArray(frame.rows)){
      this.callback.rows(frame.offset,frame.columns as string[],frame.rows as unknown[][]);
    }else if(frame.type==='result'&&typeof frame.job_id==='string'&&typeof frame.status==='string'){
      this.finalResult=frame as unknown as Job;
      if(!this.recovering&&!this.pending.size)this.finish();
      else if(!this.recovering)void this.recover();
    }else if(frame.type==='error'){this.callback.error(typeof frame.detail==='string'?frame.detail:'Stream rejected.',String(frame.error_code??''));this.close();}
  }
  private flush(){while(this.pending.has(this.cursor+1)){const event=this.pending.get(++this.cursor)!;this.pending.delete(this.cursor);this.callback.event(event);}}
  private finish(){if(this.stopped||!this.finalResult)return;this.callback.result(this.finalResult);this.close();}
  private async recover(){
    if(!this.id)return;this.recovering=true;
    try{
      for(let page=0;page<4&&this.pending.size;page++){
        const log=await api.audit(this.token,this.id,this.cursor);
        if(this.stopped)return;
        for(const event of log.events)if(event.sequence>this.cursor)this.pending.set(event.sequence,event);
        const previous=this.cursor;this.flush();if(this.cursor===previous)break;
      }
      if(this.pending.size)this.fail('Could not verify ordered event replay.');
    }catch{if(!this.stopped)this.fail('Could not verify ordered event replay.');}finally{this.recovering=false;if(!this.pending.size)this.finish();}
  }
  cancel(){if(!this.id){this.close();this.callback.state('cancelled');return false;}void api.cancel(this.token,this.id).catch(()=>{});this.send({action:'cancel',job_id:this.id});return true;}
  private fail(message:string){this.callback.error(message);this.close();}
  close(){this.stopped=true;clearTimeout(this.timer);this.socket?.close();this.queue=[];this.pending.clear();this.finalResult=undefined;}
}
