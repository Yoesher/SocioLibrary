(() => {
  let busy=false,dirty=false;
  window.isGraphNotebookBusy=()=>busy;window.isGraphNotebookDirty=()=>dirty;
  const make=(tag,text='',cls='')=>{const n=document.createElement(tag);n.textContent=text;n.className=cls;return n;};
  async function read(path){const r=await fetch(path,{headers:{'X-Sociolit-Token':token}});if(!r.ok)throw Error('读取保存图谱失败');return r.json();}
  async function work(action){if(busy)return;busy=true;el('graph-view-save').disabled=true;try{await action();}catch(e){el('graph-view-status').textContent=e.message;}finally{busy=false;el('graph-view-save').disabled=false;}}
  async function listing(){
    const rows=await read('/api/graph/views?archived='+el('graph-views-archived').checked),box=el('graph-views-list');box.replaceChildren();
    if(!rows.length)box.append(make('p','还没有保存的研究图谱。','hint'));
    for(const row of rows){const card=make('article','','graph-saved-card');card.append(make('h4',row.name),make('p',row.count+' 篇 · '+row.updated.slice(0,10),'hint'));const actions=make('div','','toolbar');
      const open=make('button','恢复视图','secondary');open.onclick=()=>work(async()=>{const saved=await read('/api/graph/views/'+row.id);window.restoreGraphView(saved);el('graph-view-status').textContent='已恢复“'+row.name+'”；关系来自保存时快照，重新探索主题可刷新。';});
      const archive=make('button',row.archived?'恢复归档':'归档视图','secondary');archive.onclick=()=>work(async()=>{await api('/api/graph/views/'+row.id+'/archive',{revision:row.revision,archived:!row.archived});await listing();});
      const exportButton=make('button','导出 Obsidian 研究包','secondary');exportButton.onclick=()=>work(async()=>{
        const include=el('graph-export-annotations').checked,bridge=window.pywebview?.api;
        if(bridge?.export_graph){const r=await bridge.export_graph(row.id,include);el('graph-view-status').textContent=r.saved?'研究包已保存到选定位置。':'已取消导出。';return;}
        const r=await fetch('/api/graph/views/'+row.id+'/export',{method:'POST',headers:{'Content-Type':'application/json','X-Sociolit-Token':token},body:JSON.stringify({include_annotations:include})});
        if(!r.ok)throw Error((await r.json()).detail||'导出失败');const url=URL.createObjectURL(await r.blob()),a=document.createElement('a');a.href=url;a.download='SocioLibrary-research.zip';a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);el('graph-view-status').textContent='研究包已交给浏览器保存，解压后可在 Obsidian 打开。';
      });actions.append(open,exportButton,archive);card.append(actions);box.append(card);
    }
  }
  el('graph-view-name').oninput=()=>{dirty=!!el('graph-view-name').value.trim();};
  el('graph-view-save').onclick=()=>work(async()=>{const name=el('graph-view-name').value.trim();if(!name)throw Error('请先填写研究图谱名称。');await api('/api/graph/views',{name,state:window.captureGraphView()});dirty=false;el('graph-view-name').value='';await listing();el('graph-view-status').textContent='已保存“'+name+'”；重开软件后可从这里恢复。';});
  el('graph-views-archived').onchange=()=>work(listing);
  document.addEventListener('workspaceview',e=>{if(e.detail==='graph-view')work(listing);});
})();
