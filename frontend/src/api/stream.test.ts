import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryStream } from './stream';
import { api } from './client';
class Socket {
  readyState=1;bufferedAmount=0;sent:string[]=[];onopen?:()=>void;onclose?:()=>void;onmessage?:(event:{data:string})=>void;onerror?:()=>void;
  send(value:string){this.sent.push(value);}close(){this.onclose?.();}
  frame(value:unknown){this.onmessage?.({data:JSON.stringify(value)});}
}
const pause=()=>Promise.resolve().then(()=>Promise.resolve());
describe('governed stream transport',()=>{
  beforeEach(()=>{vi.useFakeTimers();vi.stubGlobal('window',{location:{origin:'http://localhost:5173'}});});
  afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();vi.useRealTimers();});
  function harness(){const sockets:Socket[]=[];const callback={event:vi.fn(),rows:vi.fn(),result:vi.fn(),state:vi.fn(),error:vi.fn(),job:vi.fn()};const stream=new QueryStream('private-token','List customers',callback,url=>{expect(url).not.toContain('private-token');const socket=new Socket();sockets.push(socket);return socket as unknown as WebSocket;});stream.connect();return {stream,sockets,callback};}
  it('authenticates in a frame and starts only after ready',async()=>{const h=harness();h.sockets[0].onopen?.();expect(JSON.parse(h.sockets[0].sent[0])).toEqual({token:'private-token'});h.sockets[0].frame({type:'ready'});await pause();expect(JSON.parse(h.sockets[0].sent[1])).toEqual({action:'start',question:'List customers'});h.stream.close();});
  it('deduplicates durable events and resubscribes without repeating execution',async()=>{const h=harness();const socket=h.sockets[0];socket.onopen?.();socket.frame({type:'ready'});socket.frame({type:'job',job_id:'owned-job'});socket.frame({type:'event',sequence:1,agent:'Guardian'});socket.frame({type:'event',sequence:1,agent:'Guardian'});await pause();expect(h.callback.event).toHaveBeenCalledTimes(1);socket.close();await vi.advanceTimersByTimeAsync(800);const next=h.sockets[1];next.onopen?.();next.frame({type:'ready'});await pause();expect(JSON.parse(next.sent[1])).toEqual({action:'subscribe',job_id:'owned-job',after_sequence:1});h.stream.close();});
  it('does not resubmit after an ambiguous acknowledgement loss',async()=>{const h=harness();h.sockets[0].frame({type:'ready'});await pause();h.sockets[0].close();expect(h.callback.error).toHaveBeenCalled();await vi.advanceTimersByTimeAsync(10000);expect(h.sockets).toHaveLength(1);});
  it('cancels before acknowledgement without later starting a query',async()=>{const h=harness();expect(h.stream.cancel()).toBe(false);h.sockets[0].frame({type:'ready'});await pause();expect(h.sockets[0].sent).toHaveLength(0);expect(h.callback.state).toHaveBeenLastCalledWith('cancelled');});
  it('recovers a sequence gap from the owned audit endpoint',async()=>{const h=harness();vi.spyOn(api,'audit').mockResolvedValue({job_id:'owned-job',status:'running',events:[{sequence:1,agent:'Explorer',kind:'stage',status:'success',message:'Verified',timestamp:1,details:{}}],next_sequence:1});h.sockets[0].frame({type:'ready'});h.sockets[0].frame({type:'job',job_id:'owned-job'});h.sockets[0].frame({type:'event',sequence:2,agent:'Guardian'});await pause();await pause();expect(h.callback.event.mock.calls.map(call=>call[0].sequence)).toEqual([1,2]);h.stream.close();});
  it('delivers the final result only after an in-flight replay closes its gap',async()=>{
    const h=harness();let complete!:(value:Awaited<ReturnType<typeof api.audit>>)=>void;
    vi.spyOn(api,'audit').mockImplementation(()=>new Promise(resolve=>{complete=resolve;}));
    h.sockets[0].frame({type:'ready'});h.sockets[0].frame({type:'job',job_id:'owned-job'});
    h.sockets[0].frame({type:'event',sequence:2,agent:'Guardian'});h.sockets[0].frame({type:'result',job_id:'owned-job',status:'completed'});
    await pause();expect(h.callback.result).not.toHaveBeenCalled();
    complete({job_id:'owned-job',status:'completed',events:[{sequence:1,agent:'Explorer',kind:'stage',status:'success',message:'Verified',timestamp:1,details:{}}],next_sequence:1});
    await pause();await pause();expect(h.callback.event.mock.calls.map(call=>call[0].sequence)).toEqual([1,2]);expect(h.callback.result).toHaveBeenCalledTimes(1);
  });
  it('rejects a final result if the audit cannot close a sequence gap',async()=>{
    const h=harness();vi.spyOn(api,'audit').mockResolvedValue({job_id:'owned-job',status:'completed',events:[],next_sequence:0});
    h.sockets[0].frame({type:'ready'});h.sockets[0].frame({type:'job',job_id:'owned-job'});h.sockets[0].frame({type:'event',sequence:2,agent:'Guardian'});h.sockets[0].frame({type:'result',job_id:'owned-job',status:'completed'});
    await pause();await pause();expect(h.callback.result).not.toHaveBeenCalled();expect(h.callback.error).toHaveBeenCalledWith('Could not verify ordered event replay.');
  });
});
