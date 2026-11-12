/* One status request at a time. Hidden pages pause; idle pages poll less often. */
((root) => {
  function create({read, visible, installing, onError, setTimer=setTimeout, clearTimer=clearTimeout}) {
    let current=null, queued=null, timer=null, running=false, halted=false, busy=false, failures=0;
    function clear() {if(timer!==null)clearTimer(timer);timer=null;}
    function schedule() {
      clear();
      if(!running||!visible())return;
      const delay=installing()?1000:failures?Math.min(30000,2500*2**Math.min(failures,4)):(busy?2500:10000);
      timer=setTimer(()=>{timer=null;automatic().catch(onError);},delay);
    }
    function execute() {
      if(halted||installing())return Promise.resolve();
      clear();
      const task=Promise.resolve().then(read).then(value=>{
        failures=0;
        busy=Boolean(value&&(value.library_busy||value.job?.state==='running'||
          ['checking','downloading'].includes(value.software_update?.state)));
        return value;
      }).catch(error=>{failures++;throw error;}).finally(()=>{
        if(current===task)current=null;
        schedule();
      });
      current=task;
      return task;
    }
    function automatic() {
      if(!running||!visible())return Promise.resolve();
      if(installing()){schedule();return Promise.resolve();}
      return current||execute();
    }
    function refresh() {
      if(!current)return execute();
      // An explicit refresh after a write must run after the older read, while
      // repeated timer/focus events simply share the in-flight request.
      if(!queued)queued=current.catch(()=>{}).then(()=>{queued=null;return execute();});
      return queued;
    }
    return {
      refresh,
      start(){halted=false;running=true;return automatic();},
      stop(){halted=true;running=false;clear();},
      wake(){clear();return automatic().catch(onError);}
    };
  }
  if(typeof module==='object'&&module.exports)module.exports={create};
  else root.StatusPolling={create};
})(typeof window==='object'?window:globalThis);
