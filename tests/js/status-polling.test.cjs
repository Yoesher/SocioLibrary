const test=require('node:test');
const assert=require('node:assert/strict');
const {create}=require('../../src/sociolit/static/status-polling.js');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function deferred(){let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve};}
function setup(read){
  const timers=new Map(),errors=[];let next=0,visible=true,installing=false;
  const poll=create({read,visible:()=>visible,installing:()=>installing,onError:e=>errors.push(e),
    setTimer:(fn,ms)=>{timers.set(++next,{fn,ms});return next;},clearTimer:id=>timers.delete(id)});
  return {poll,timers,errors,setVisible:value=>visible=value,setInstalling:value=>installing=value,
    fire(){const [id,value]=timers.entries().next().value;timers.delete(id);value.fn();return value.ms;},
    delay(){return timers.values().next().value?.ms;}};
}
test('idle polling backs off, active jobs stay responsive, hidden and installing pages avoid requests',async()=>{
  let count=0,busy=false;const s=setup(async()=>{count++;return {job:{state:busy?'running':'done'}};});
  await s.poll.start();assert.equal(s.delay(),10000);
  busy=true;s.fire();await flush();assert.equal(s.delay(),2500);
  s.setVisible(false);await s.poll.wake();assert.equal(s.timers.size,0);assert.equal(count,2);
  s.setVisible(true);await s.poll.wake();assert.equal(count,3);
  s.setInstalling(true);s.fire();await flush();assert.equal(count,3);assert.equal(s.delay(),1000);
  s.setInstalling(false);s.fire();await flush();assert.equal(count,4);
  s.poll.stop();assert.equal(s.timers.size,0);
});
test('slow reads never overlap and a post-write refresh queues one fresh read',async()=>{
  const requests=[];let active=0,maximum=0;
  const s=setup(()=>{const d=deferred();requests.push(d);active++;maximum=Math.max(maximum,active);return d.promise.finally(()=>active--);});
  const first=s.poll.start();await flush();
  s.poll.wake();s.poll.wake();const afterWrite=s.poll.refresh();assert.equal(afterWrite,s.poll.refresh());
  assert.equal(requests.length,1);
  requests[0].resolve({});await first;await flush();assert.equal(requests.length,2);
  requests[1].resolve({});await afterWrite;assert.equal(maximum,1);assert.equal(s.timers.size,1);
  s.poll.stop();
});
test('failed connections use bounded retry delays and recover without restarting',async()=>{
  let fail=true;const s=setup(async()=>{if(fail)throw Error('offline');return {};});
  await assert.rejects(s.poll.start());assert.equal(s.delay(),5000);
  for(const delay of [10000,20000,30000,30000]){s.fire();await flush();assert.equal(s.delay(),delay);}
  fail=false;s.fire();await flush();assert.equal(s.delay(),10000);s.poll.stop();
});
test('closing a page cancels queued refreshes and leaves no periodic work',async()=>{
  const d=deferred();let count=0;const s=setup(()=>{count++;return d.promise;});
  const first=s.poll.start();await flush();const queued=s.poll.refresh();s.poll.stop();d.resolve({});
  await Promise.all([first,queued]);assert.equal(count,1);assert.equal(s.timers.size,0);
  await s.poll.wake();assert.equal(count,1);
});
