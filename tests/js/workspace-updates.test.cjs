const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const vm=require('node:vm');
const source=readFileSync('src/sociolit/static/workspace.js','utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));

async function app(mode='installed'){
  const nodes=new Map(),calls=[],views=[],dirty={ai:false,appearance:false,comparison:false};
  const node=()=>({value:'',checked:false,disabled:false,hidden:false,textContent:'',children:[],listeners:{},
    addEventListener(event,fn){(this.listeners[event]??=[]).push(fn);},
    append(...items){this.children.push(...items);},replaceChildren(...items){this.children=[...items];},
    scrollIntoView(){this.scrolled=true;},click(){return this.onclick?.();}});
  const el=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);};
  const window={addEventListener(){},isAISettingsDirty:()=>dirty.ai,isAppearanceDirty:()=>dirty.appearance,
    isLiteratureDirty:()=>dirty.comparison,pywebview:{api:{
      update_context:async()=>({mode,supported:mode!=='macos',message:''}),
      install_update:async()=>calls.push('install'),open_releases:async()=>calls.push('mac-download')
    }}};
  const status={pdf_roots:[],collection_keywords:[],job:{state:'done'},library_busy:false,
    software_update:{state:'available',current_version:'1.0.0',available_version:'1.0.1',auto_check:true}};
  const context={window,el,token:'synthetic',settingsLoaded:true,searchBusy:false,
    showView:id=>views.push(id),notice:text=>calls.push(text),
    document:{createElement:node,querySelector:()=>node(),querySelectorAll:()=>[],addEventListener(){}},
    api:async path=>{calls.push(path);status.software_update.state='ready';},
    refresh:async()=>window.renderSoftwareUpdate(status)};
  vm.runInNewContext(source,context);await tick();window.renderSoftwareUpdate(status);
  return {window,el,calls,views,dirty,status,async click(id='software-upgrade'){await el(id).onclick();await tick();}};
}

test('unsaved AI settings allow download, block installation and link to exact editor',async()=>{
  const a=await app();a.dirty.ai=true;await a.click();
  assert.ok(a.calls.includes('/api/software-update/download'));
  assert.ok(!a.calls.includes('install'));
  assert.match(a.el('software-progress-text').textContent,/已下载并核对/);
  const rows=a.el('software-blockers-list').children;
  assert.equal(rows.length,1);assert.match(rows[0].children[0].textContent,/AI 连接/);
  rows[0].children[1].onclick();assert.ok(a.views.includes('ai-view'));
  assert.equal(a.dirty.ai,true,'navigation must not discard edits');
  a.dirty.ai=false;await a.click();assert.equal(a.calls.filter(x=>x==='install').length,1);
});

test('portable banner starts download and clean installation instead of only switching pages',async()=>{
  const a=await app('portable');assert.match(a.el('software-banner-go').textContent,/安装版/);
  await a.click('software-banner-go');
  assert.ok(a.calls.includes('/api/software-update/download'));assert.ok(a.calls.includes('install'));
});

test('notes, appearance and comparison basket remain protected after downloading',async()=>{
  const a=await app();a.el('note-body').listeners.input[0]();a.dirty.appearance=true;a.dirty.comparison=true;
  await a.click();assert.ok(a.calls.includes('/api/software-update/download'));assert.ok(!a.calls.includes('install'));
  assert.deepEqual(Array.from(a.window.getUpgradeBlockers(),r=>r.key),['note','appearance','comparison']);
  a.el('software-later').onclick();a.el('new-note').listeners.click[0]();a.dirty.appearance=false;a.dirty.comparison=false;
  a.window.renderSoftwareUpdate(a.status);await tick();assert.ok(!a.calls.includes('install'),'later means no automatic installation');
});

test('background jobs defer installation until finished; Mac opens the Mac download page',async()=>{
  const a=await app();a.status.job.state='running';await a.click();assert.ok(!a.calls.includes('install'));
  a.status.job.state='done';a.window.renderSoftwareUpdate(a.status);await tick();assert.ok(a.calls.includes('install'));
  const mac=await app('macos');await mac.click('software-banner-go');assert.deepEqual(mac.calls,['mac-download']);
});
