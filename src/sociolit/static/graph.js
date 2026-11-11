(() => {
  const NS='http://www.w3.org/2000/svg';
  let data=null, seed='', selected='', busy=false, writing=false, linkDirty=false, transform={x:0,y:0,k:1};
  const positions=new Map();
  async function mutateLink(path,payload){writing=true;try{return await api(path,payload);}finally{writing=false;}}
  window.isGraphBusy=()=>busy||writing;window.isGraphDirty=()=>linkDirty;el('graph-link-form').addEventListener('input',()=>{linkDirty=true;});
  const svg=el('literature-graph'), world=document.createElementNS(NS,'g');const defs=makeDefs();svg.append(defs,world);
  function makeDefs(){const d=document.createElementNS(NS,'defs'),m=document.createElementNS(NS,'marker');for(const [k,v] of Object.entries({id:'graph-arrow',viewBox:'0 0 10 10',refX:19,refY:5,markerWidth:7,markerHeight:7,orient:'auto'}))m.setAttribute(k,v);const p=document.createElementNS(NS,'path');p.setAttribute('d','M 0 0 L 10 5 L 0 10 z');p.setAttribute('class','graph-arrow');m.append(p);d.append(m);return d;}
  const make=(tag,attrs={})=>{const e=document.createElementNS(NS,tag);for(const [key,value] of Object.entries(attrs))e.setAttribute(key,String(value));return e;};
  function camera(){world.setAttribute('transform',`translate(${transform.x} ${transform.y}) scale(${transform.k})`);}
  function arrange(){
    positions.clear();const n=data.nodes.length;
    data.nodes.forEach((node,i)=>{const angle=i*2.39996323,radius=60+235*Math.sqrt((i+.5)/Math.max(n,1));positions.set(node.id,{x:470+radius*Math.cos(angle),y:330+radius*.85*Math.sin(angle)});});
    // A finite layout, not a perpetual animation. Work is bounded by 80 nodes.
    for(let step=0;step<120;step++){
      const force=new Map(data.nodes.map(n=>[n.id,{x:0,y:0}]));
      for(let i=0;i<n;i++)for(let j=i+1;j<n;j++){
        const a=positions.get(data.nodes[i].id),b=positions.get(data.nodes[j].id),dx=a.x-b.x,dy=a.y-b.y,d2=Math.max(dx*dx+dy*dy,100),strength=160/d2;
        force.get(data.nodes[i].id).x+=dx*strength;force.get(data.nodes[i].id).y+=dy*strength;
        force.get(data.nodes[j].id).x-=dx*strength;force.get(data.nodes[j].id).y-=dy*strength;
      }
      for(const edge of data.edges){const a=positions.get(edge.source),b=positions.get(edge.target);if(!a||!b)continue;const dx=b.x-a.x,dy=b.y-a.y,dist=Math.max(Math.hypot(dx,dy),1),v=(dist-155)*.012;force.get(edge.source).x+=dx/dist*v;force.get(edge.source).y+=dy/dist*v;force.get(edge.target).x-=dx/dist*v;force.get(edge.target).y-=dy/dist*v;}
      for(const node of data.nodes){const p=positions.get(node.id),f=force.get(node.id);p.x=Math.max(95,Math.min(850,p.x+Math.max(-9,Math.min(9,f.x+(470-p.x)*.035))));p.y=Math.max(60,Math.min(585,p.y+Math.max(-9,Math.min(9,f.y+(330-p.y)*.035))));}
    }
  }
  function detail(node){
    selected=node.id;el('graph-detail').replaceChildren();const h=document.createElement('h3');h.textContent=node.title;
    const p=document.createElement('p');p.textContent=[(node.authors||[]).join('、'),node.year,node.current?'当前书目':'来源已不在本机书目，保留关系快照'].filter(Boolean).join(' · ');
    el('graph-detail').append(h,p);
    const neighbors=data.edges.filter(e=>e.source===node.id||e.target===node.id);
    for(const edge of neighbors){const row=document.createElement('article');row.className='graph-relation';const other=data.nodes.find(n=>n.id===(edge.source===node.id?edge.target:edge.source));const text=document.createElement('p');text.textContent=(edge.kind==='cites'&&edge.target===node.id?'被引用（本人确认） ← ':edge.label+' → ')+(other?.title||'未知文献')+(edge.note?' · '+edge.note:'')+(edge.archived?'（已归档）':'');row.append(text);
      if(edge.origin==='manual'){const button=document.createElement('button');button.className='secondary';button.textContent=edge.archived?'恢复关系':'归档关系';button.onclick=async()=>{try{await mutateLink('/api/graph/links/archive',{identity:edge.id,revision:edge.revision,archived:!edge.archived});await load();}catch(error){notice(error.message,true);}};row.append(button);}el('graph-detail').append(row);}
    if(!neighbors.length){const p=document.createElement('p');p.textContent='本视图中尚无连线，可以手动建立关系。';el('graph-detail').append(p);}
    if(node.current){const button=document.createElement('button');button.className='secondary';button.textContent='围绕此文献查看';button.onclick=()=>{seed=node.id;load();};el('graph-detail').append(button);
      const search=document.createElement('button');search.className='secondary';search.textContent='查看原文片段';search.onclick=()=>{el('query').value=node.title.slice(0,200);el('mode').value='auto';showView('search-view');el('search').requestSubmit();};el('graph-detail').append(search);}
    world.querySelectorAll('.graph-node').forEach(group=>group.classList.toggle('selected',group.dataset.id===node.id));
  }
  function draw(){
    world.replaceChildren();world.classList.toggle('dense',data.nodes.length>35);const degrees=new Map();
    for(const edge of data.edges){degrees.set(edge.source,(degrees.get(edge.source)||0)+1);degrees.set(edge.target,(degrees.get(edge.target)||0)+1);const a=positions.get(edge.source),b=positions.get(edge.target);if(!a||!b)continue;const line=make('line',{x1:a.x,y1:a.y,x2:b.x,y2:b.y,class:'graph-edge '+edge.origin,'marker-end':edge.kind==='cites'?'url(#graph-arrow)':''});const title=make('title');title.textContent=edge.label+(edge.note?' · '+edge.note:'');line.append(title);world.append(line);}
    for(const node of data.nodes){const p=positions.get(node.id),group=make('g',{transform:`translate(${p.x} ${p.y})`,class:'graph-node'+(!node.current?' missing':''),tabindex:0,role:'button','aria-label':node.title});group.dataset.id=node.id;
      const hit=make('rect',{x:-28,y:-24,width:56,height:60,fill:'transparent'});const circle=make('circle',{r:Math.min(20,12+Math.sqrt(degrees.get(node.id)||0)*2)});const label=make('text',{x:0,y:32,'text-anchor':'middle'});const max=/[\u3400-\u9fff]/.test(node.title)?9:20;label.textContent=node.title.length>max?node.title.slice(0,max)+'…':node.title;const title=make('title');title.textContent=node.title;group.append(hit,circle,label,title);
      group.onclick=()=>detail(node);group.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();detail(node);}};
      group.onpointerdown=e=>{if(e.button!==0)return;e.stopPropagation();group.setPointerCapture(e.pointerId);let moved=false;const move=event=>{if(Math.abs(event.movementX)+Math.abs(event.movementY)>1)moved=true;const rect=svg.getBoundingClientRect();p.x+=(event.movementX*940/rect.width)/transform.k;p.y+=(event.movementY*650/rect.height)/transform.k;group.setAttribute('transform',`translate(${p.x} ${p.y})`);};group.onpointermove=move;group.onpointerup=()=>{group.onpointermove=null;if(moved)draw();else detail(node);};};world.append(group);}
    camera();if(selected){const node=data.nodes.find(n=>n.id===selected);if(node)detail(node);}
    el('graph-paper-list').replaceChildren();for(const node of data.nodes){const button=document.createElement('button');button.className='graph-list-item';button.textContent=node.title;button.onclick=()=>detail(node);el('graph-paper-list').append(button);}
  }
  async function load(){
    if(busy)return;busy=true;el('graph-load').disabled=true;
    try{data=await api('/api/graph',{query:seed?'':el('graph-query').value.trim(),seed,limit:Number(el('graph-limit').value),include_auto:el('graph-auto').checked,include_archived:el('graph-archived').checked});arrange();transform={x:0,y:0,k:1};draw();el('graph-summary').textContent=`${data.nodes.length} 篇文献 · ${data.edges.length} 条关系${data.limited?' · 已达显示上限，可缩小主题':''}。${data.message}`;if(!data.nodes.length)el('graph-detail').textContent='暂未找到匹配书目。请更换题名或标签关键词。';}catch(error){notice(error.message,true);}finally{busy=false;el('graph-load').disabled=false;}
  }
  window.openLiteratureGraph=id=>{seed=id;showView('graph-view');load();};
  window.enhanceGraphResult=(box,source)=>{const button=document.createElement('button');button.className='text-button';button.textContent='查看文献关联';button.onclick=()=>window.openLiteratureGraph(source.item_id);box.append(button);};
  el('graph-form').onsubmit=event=>{event.preventDefault();seed='';selected='';load();};
  el('graph-reset').onclick=()=>{transform={x:0,y:0,k:1};camera();};
  function zoom(value){transform.k=Math.max(.45,Math.min(2.5,transform.k*value));camera();}
  el('graph-zoom-in').onclick=()=>zoom(1.2);el('graph-zoom-out').onclick=()=>zoom(1/1.2);
  svg.addEventListener('wheel',event=>{event.preventDefault();zoom(event.deltaY<0?1.12:1/1.12);},{passive:false});
  svg.onpointerdown=event=>{if(event.target.closest('.graph-node'))return;svg.setPointerCapture(event.pointerId);svg.onpointermove=e=>{const rect=svg.getBoundingClientRect();transform.x+=e.movementX*940/rect.width;transform.y+=e.movementY*650/rect.height;camera();};};svg.onpointerup=()=>{svg.onpointermove=null;};svg.onpointercancel=svg.onpointerup;
  svg.onkeydown=event=>{if(event.target!==svg)return;if(event.key==='+'||event.key==='=')zoom(1.2);else if(event.key==='-')zoom(1/1.2);else if(['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(event.key)){event.preventDefault();transform.x+=event.key==='ArrowLeft'?25:event.key==='ArrowRight'?-25:0;transform.y+=event.key==='ArrowUp'?25:event.key==='ArrowDown'?-25:0;camera();}};
  async function lookup(){try{const response=await fetch('/api/literature/catalog?query='+encodeURIComponent(el('graph-link-query').value),{headers:{'X-Sociolit-Token':token}});if(!response.ok)throw Error('查找文献失败');const values=await response.json();for(const key of ['graph-link-source','graph-link-target']){const previous=el(key).value, keep=Array.from(el(key).options).find(o=>o.value===previous);el(key).replaceChildren();const merged=new Map(values.map(v=>[v.id,v.title]));if(keep)merged.set(keep.value,keep.textContent);for(const [id,title] of merged){const option=document.createElement('option');option.value=id;option.textContent=title;el(key).append(option);}if(keep)el(key).value=previous;else if(key==='graph-link-target'&&values.length>1)el(key).selectedIndex=1;}el('graph-link-hint').textContent=`找到 ${values.length} 篇，最多显示30篇。选择两篇并说明关系；可继续查找另一题名，已选项会保留。`;}catch(error){notice(error.message,true);}}
  el('graph-link-lookup').onclick=lookup;el('graph-link-reset').onclick=()=>{el('graph-link-form').reset();linkDirty=false;notice('已清空未保存关系输入。');};
  el('graph-link-form').onsubmit=async event=>{event.preventDefault();try{await mutateLink('/api/graph/links',{source:el('graph-link-source').value,target:el('graph-link-target').value,kind:el('graph-link-kind').value,note:el('graph-link-note').value});seed=el('graph-link-source').value;await load();linkDirty=false;notice('关系已保存到本机。');}catch(error){notice(error.message,true);}};
  document.querySelector('[data-view="graph-view"]').addEventListener('click',()=>{load();});
})();
