/* Incremental, local-only graph explorer. No model loading or remote assets. */
(() => {
  const C=GraphCore,make=(tag,text='',cls='')=>{const n=document.createElement(tag);n.textContent=text;n.className=cls;return n;};
  let savedStamp='',data=null,seed='',currentQuery='',selected='',busy=false,writing=false,linkDirty=false,cy=null,immersivePreferred=false;
  let origin='all',motion=true,opening=false,requestId=0,controller=null,simulation=0,layoutJob=null,minimapTimer=0,layoutVersion=0,fitWhenSettled=false,freshTimer=0,cameraTimer=0;
  let applied={limit:'15',auto:true,archived:false};
  let pinned=new Set(),dragging=new Set(),dragged=new Set(),past=[],future=[],mapTransform=null,lastTap={id:'',time:0};
  const reduced=matchMedia('(prefers-reduced-motion: reduce)'),isMoving=()=>!reduced.matches&&document.documentElement.dataset.motion!=='none';
  const colors=()=>{const s=getComputedStyle(document.documentElement);return [s.getPropertyValue('--graph-dot').trim(),...Array.from({length:5},(_,i)=>s.getPropertyValue('--graph-group-'+(i+1)).trim())];};
  const names={all:'全部',manual:'本人确认',words:'标签与词语',semantic:'语义线索',comparison:'比较表'};
  const sourceName={manual:'本人建立',metadata:'书目共同词语',tags:'共享标签',title:'题名词语',semantic:'本机语义',comparison:'比较表'};
  window.isGraphBusy=()=>busy||writing||Boolean(window.isGraphNotebookBusy?.());window.isGraphDirty=()=>linkDirty;
  el('graph-link-form').addEventListener('input',()=>{linkDirty=true;});
  async function mutateLink(path,payload){writing=true;try{return await api(path,payload);}finally{writing=false;}}
  function styles(){const s=getComputedStyle(document.documentElement),c=k=>s.getPropertyValue('--'+k).trim();return [
    {selector:'node',style:{shape:'ellipse',width:'data(renderSize)',height:'data(renderSize)','background-color':'data(color)','background-opacity':1,'border-width':.8,'border-color':c('graph-canvas'),label:'data(label)','font-size':'data(fontSize)','font-family':'Segoe UI, Microsoft YaHei, sans-serif','font-weight':400,color:c('muted'),'text-opacity':.9,'text-valign':'center','text-halign':'right','text-margin-x':'data(labelGap)','text-wrap':'ellipsis','text-max-width':'data(labelWidth)','text-overflow-wrap':'anywhere','text-outline-color':c('graph-canvas'),'text-outline-width':2,'min-zoomed-font-size':0,'overlay-opacity':0,'overlay-padding':7,'ghost':'no','transition-property':'opacity, background-color, line-color','transition-duration':isMoving()?140:0}},
    {selector:'node.center',style:{'background-color':c('accent'),'border-width':1.2}},
    {selector:'node.missing',style:{'background-opacity':.2,'border-color':'data(color)','border-style':'dashed',opacity:.7}},
    {selector:'node.pinned',style:{'underlay-color':'data(color)','underlay-opacity':.13,'underlay-padding':4,'underlay-shape':'ellipse'}},
    {selector:'node.fresh',style:{'underlay-color':c('accent'),'underlay-opacity':.16,'underlay-padding':5,'underlay-shape':'ellipse'}},
    {selector:'edge',style:{width:.8,'line-color':c('graph-line'),opacity:.5,'curve-style':'bezier','line-style':'solid','overlay-opacity':0}},
    {selector:'edge[origin="manual"]',style:{'line-color':c('accent'),opacity:.65,width:1.2,'line-style':'solid'}},
    {selector:'edge[kind="cites"]',style:{'target-arrow-shape':'triangle','target-arrow-color':c('accent')}},
    {selector:'edge[origin="comparison"]',style:{'line-color':c('graph-group-2'),'line-style':'dotted',opacity:.55}},
    {selector:'edge[origin="semantic"]',style:{'line-color':c('graph-group-1'),opacity:.5}},
    {selector:'node.dimmed',style:{opacity:.28}},
    {selector:'edge.dimmed',style:{opacity:.08}},
    {selector:'node.focused, node.hovered',style:{color:c('text'),'text-opacity':1}},
    {selector:'edge.focused, edge.hovered',style:{'line-color':c('accent'),opacity:.65,width:1.1}},
    {selector:'node:selected',style:{'background-color':c('accent'),'border-width':1.2,'underlay-color':c('accent'),'underlay-opacity':.12,'underlay-padding':6,'underlay-shape':'ellipse',color:c('text'),'font-weight':600,'text-opacity':1,'min-zoomed-font-size':0}},
    {selector:'.filtered',style:{display:'none'}},
    {selector:'node.labels-off, node.labels-hidden',style:{label:''}},
    {selector:'node.labels-off:selected,node.labels-off.hovered,node.labels-hidden:selected,node.labels-hidden.hovered',style:{label:'data(label)','min-zoomed-font-size':0}}
  ];}
  function activity(text,running=false){el('graph-activity').textContent=text;el('graph-activity').dataset.running=String(running);}
  function stopSimulation(text='布局已稳定'){if(simulation)cancelAnimationFrame(simulation);simulation=0;activity(text);}
  function clearMotion(){if(cameraTimer)clearTimeout(cameraTimer);layoutVersion++;fitWhenSettled=false;stopSimulation();if(layoutJob){layoutJob.stop();layoutJob=null;}cy?.stop();cy?.nodes().stop();}
  function visibleData(){return C.visible(data,origin,el('graph-orphans').checked);}
  function simulate(){
    stopSimulation();if(!cy||!data||busy||!motion||!isMoving()||el('graph-view').hidden||document.hidden||el('graph-layout').value!=='network'){activity(!isMoving()?'已减少动画':'布局就绪');return;}
    const view=visibleData(),points=view.nodes.map(n=>({id:n.id,...cy.getElementById(n.id).position(),vx:0,vy:0}));if(!points.length)return;
    const center={x:points.reduce((v,p)=>v+p.x,0)/points.length,y:points.reduce((v,p)=>v+p.y,0)/points.length};let tick=0,last=0;
    activity('动态舒展中',true);
    const frame=time=>{
      if(el('graph-view').hidden||document.hidden||!motion||!isMoving()){stopSimulation('动态已暂停');return;}
      if(time-last>=32){
        last=time;tick++;for(const p of points){p.pinned=pinned.has(p.id)||dragging.has(p.id);if(p.pinned)Object.assign(p,cy.getElementById(p.id).position());}
        const energy=C.step(points,view.edges,center,Number(el('graph-spacing').value)/100);
        cy.batch(()=>{for(const p of points)if(!p.pinned)cy.getElementById(p.id).position({x:p.x,y:p.y});});
        if(tick>=210||(tick>65&&energy<.018)){const autoFit=fitWhenSettled;fitWhenSettled=false;stopSimulation();if(autoFit)fit();return;}
      }
      simulation=requestAnimationFrame(frame);
    };simulation=requestAnimationFrame(frame);
  }
  function camera(id,zoom){fitWhenSettled=false;if(!cy)return;const node=cy.getElementById(id);if(!node.length||node.hasClass('filtered'))return;const p=node.position(),z=zoom||Math.max(cy.zoom(),.95),pan={x:cy.width()/2-p.x*z,y:cy.height()/2-p.y*z};cy.stop();if(isMoving())cy.animate({zoom:z,pan},{duration:320});else{cy.zoom(z);cy.pan(pan);}}
  function fit(){fitWhenSettled=false;if(!cy)return;cy.resize();const eles=cy.elements().not('.filtered');if(!eles.length)return;cy.stop();if(isMoving())cy.animate({fit:{eles,padding:55}},{duration:380});else cy.fit(eles,55);}
  function record(){if(!data)return null;return C.clone({savedStamp,data,seed,currentQuery,selected,positions:Object.fromEntries(cy.nodes().map(n=>[n.id(),n.position()])),pinned:[...pinned],viewport:{zoom:cy.zoom(),pan:cy.pan()},origin,layout:el('graph-layout').value,orphans:el('graph-orphans').checked,query:currentQuery,limit:applied.limit,auto:applied.auto,archived:applied.archived});}
  function checkpoint(){const value=record();if(value){past.push(value);if(past.length>12)past.shift();}future=[];historyButtons();}
  function pinControl(){el('graph-unpin').disabled=!pinned.size;el('graph-unpin').textContent=pinned.size?'释放固定 ('+pinned.size+')':'释放固定';}
  function historyButtons(){el('graph-back').disabled=busy||!past.length;el('graph-forward').disabled=busy||!future.length;}
  function historyMove(back){if(busy)return;const from=back?past:future,to=back?future:past;if(!from.length)return;const current=record();if(current)to.push(current);const state=from.pop();clearMotion();savedStamp=state.savedStamp||'';seed=state.seed;currentQuery=state.currentQuery;selected=state.selected;origin=state.origin;pinned=new Set(state.pinned);el('graph-layout').value=state.layout;el('graph-orphans').checked=state.orphans;el('graph-query').value=state.query;el('graph-limit').value=state.limit;el('graph-auto').checked=state.auto;el('graph-archived').checked=state.archived;applied={limit:state.limit,auto:state.auto,archived:state.archived};render(state.data,true);cy.nodes().forEach(n=>{if(state.positions[n.id()])n.position(state.positions[n.id()]);});cy.zoom(state.viewport.zoom);cy.pan(state.viewport.pan);activity('已返回探索位置');syncMotionControl();historyButtons();}
  async function request(path,payload){
    const id=++requestId;controller?.abort();controller=new AbortController();const ownController=controller;busy=true;clearMotion();el('graph-load').disabled=true;historyButtons();activity('正在查找关联');
    try{if(!token){const status=await fetch('/api/status').then(r=>r.json());token=status.token;}
      const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Sociolit-Token':token},body:JSON.stringify(payload),signal:ownController.signal});const value=await response.json();if(!response.ok)throw Error(typeof value.detail==='string'?value.detail:'图谱请求失败');return id===requestId?value:null;
    }catch(error){if(error.name!=='AbortError'&&id===requestId){notice(error.message,true);activity('原视图已保留');}return null;}
    finally{if(id===requestId){busy=false;el('graph-load').disabled=false;historyButtons();}}
  }
  function filters(){
    if(!cy||!data)return;clearMotion();const view=visibleData(),nodeIds=new Set(view.nodes.map(n=>n.id)),edgeIds=new Set(view.edges.map(C.edgeKey));
    cy.batch(()=>{cy.nodes().forEach(n=>n.toggleClass('filtered',!nodeIds.has(n.id())));cy.edges().forEach(e=>e.toggleClass('filtered',!edgeIds.has(e.data('key'))));cy.nodes().toggleClass('labels-off',!el('graph-labels').checked);});
    for(const button of document.querySelectorAll('[data-graph-origin]')){const key=button.dataset.graphOrigin;button.setAttribute('aria-pressed',String(origin===key));button.textContent=names[key]+' '+C.visible(data,key,true).edges.length;}
    el('graph-empty').hidden=!!view.edges.length||!!view.nodes.length;el('graph-minimap').hidden=!el('graph-minimap-visible').checked||!view.nodes.length;
    el('graph-summary').textContent=`图中 ${view.nodes.length} / ${data.nodes.length} 篇 · ${view.edges.length} 条关系`+(data.nodes.length>=80?' · 已达80篇上限':data.limited?' · 可选择节点继续展开':'')+(data.edges_limited?' · 连线已达显示上限，请缩小主题':'');
    el('graph-context').textContent=seed?'围绕《'+(data.nodes.find(n=>n.id===seed)?.title||'文献')+'》探索':currentQuery?'研究主题：'+currentQuery:'文献概览 · 优先展示已有联系的书目';if(savedStamp)el('graph-context').textContent+=' · 保存时快照 '+savedStamp;
    if(selected){if(nodeIds.has(selected))highlight(selected);else{cy.nodes().unselect();cy.elements().removeClass('dimmed focused hovered');}}else clearSelection();renderList();scheduleMap();
  }
  function highlight(id,hover=false){if(!cy)return;cy.elements().removeClass('dimmed focused hovered');const node=cy.getElementById(id);if(!node.length||node.hasClass('filtered'))return;const connected=node.closedNeighborhood().not('.filtered');cy.elements().not('.filtered').not(connected).addClass('dimmed');connected.addClass(hover?'hovered':'focused');}
  function clearSelection(){selected='';scheduleMap();cy?.nodes().unselect();cy?.elements().removeClass('dimmed focused hovered');emptyDetail();syncListSelection();}
  function emptyDetail(){const panel=el('graph-detail');panel.replaceChildren();const box=make('div','','graph-detail-empty');box.append(make('span','⌘','graph-detail-symbol'),make('span','文献探索','graph-inspector-kicker'),make('h3','从一篇文献，走向下一篇。'),make('p','点击节点查看关系依据，再展开关联。拖动节点会固定位置；双击可阅读摘要与原文。'));panel.append(box);}
  function detail(node){
    selected=node.id;el('graph-detail').scrollTop=0;pinControl();scheduleMap();cy.nodes().unselect();cy.getElementById(node.id).select();highlight(node.id);syncListSelection();
    const panel=el('graph-detail');panel.replaceChildren(make('span',node.current?'当前文献':'保留的书目快照','graph-inspector-kicker'),make('h3',node.title),make('p',[(node.authors||[]).join('、'),node.year].filter(Boolean).join(' · ')));
    if(cy.getElementById(node.id).hasClass('filtered')){panel.append(make('p','这篇文献被当前筛选隐藏，选择仍保留。'));const reveal=make('button','显示这篇文献','secondary');reveal.onclick=()=>{origin='all';el('graph-orphans').checked=true;filters();detail(node);camera(node.id);};panel.append(reveal);return;}
    const neighbors=visibleData().edges.filter(e=>e.source===node.id||e.target===node.id),unique=new Set(neighbors.map(e=>e.source===node.id?e.target:e.source));panel.append(make('span',`${unique.size} 篇相邻文献 · ${neighbors.length} 条线索`,'graph-node-count'));
    const actions=make('div','','graph-inspector-actions');
    if(node.current){
      const expand=make('button','展开 8 篇关联','graph-expand-action');expand.disabled=busy||data.nodes.length>=80;expand.onclick=()=>expandNode(node.id);
      const focus=make('button','以此为中心','secondary');focus.onclick=()=>load({seed:node.id,query:''});
      const read=make('button','摘要与原文','secondary');read.onclick=()=>window.openPaper(node.id,node.title);actions.append(expand,focus,read);
    }
    const pin=make('button',pinned.has(node.id)?'取消固定':'固定位置','secondary');pin.setAttribute('aria-pressed',String(pinned.has(node.id)));pin.onclick=()=>{if(pinned.has(node.id))pinned.delete(node.id);else pinned.add(node.id);cy.getElementById(node.id).toggleClass('pinned',pinned.has(node.id));detail(node);simulate();};actions.append(pin);panel.append(actions);
    if(!neighbors.length)panel.append(make('p','当前筛选下还没有连线。可以展开关联、切换来源，或在下方建立人工关系。'));
    const relations=new Map();for(const edge of neighbors.slice().sort((a,b)=>(a.origin==='manual'?0:1)-(b.origin==='manual'?0:1))){const id=edge.source===node.id?edge.target:edge.source;if(!relations.has(id))relations.set(id,[]);relations.get(id).push(edge);}
    for(const [id,edges] of relations){
      const other=data.nodes.find(n=>n.id===id),row=make('article','','graph-relation'),title=make('button',other?.title||'未知文献','text-button');
      title.onclick=()=>{if(other){detail(other);camera(other.id);}};row.append(title);
      for(const edge of edges){
        row.append(make('small',(edge.snapshot?'保存时快照 · ':'')+(sourceName[edge.origin]||'关系线索')),make('p',(edge.kind==='cites'&&edge.target===node.id?'被引用（本人确认）':edge.label)+(edge.note?' · '+edge.note:'')));
        if(edge.origin==='manual'&&!edge.snapshot){const archive=make('button',edge.archived?'恢复关系':'归档关系','secondary');archive.onclick=async()=>{try{await mutateLink('/api/graph/links/archive',{identity:edge.id,revision:edge.revision,archived:!edge.archived});await load();}catch(error){notice(error.message,true);}};row.append(archive);}
      }panel.append(row);
    }

  }
  function detailEdge(edge){
    cy.elements().removeClass('dimmed focused hovered');const key=C.edgeKey(edge),line=cy.edges().filter(e=>e.data('key')===key);cy.elements().not(line.connectedNodes().union(line)).addClass('dimmed');line.addClass('focused');
    const panel=el('graph-detail');panel.replaceChildren(make('span',sourceName[edge.origin]||'关联依据','graph-inspector-kicker'),make('h3',edge.label),make('p',edge.note||'这条线索来自本机已导入资料。'));
    if(edge.origin!=='manual')panel.append(make('p','自动线索仅帮助发现候选，不表示引用、因果或结论一致。'));
    for(const id of [edge.source,edge.target]){const node=data.nodes.find(n=>n.id===id),b=make('button',node.title,'text-button');b.onclick=()=>{detail(node);camera(id);};panel.append(make('p','连接的文献'),b);}
  }
  function tooltip(node){const box=el('graph-tooltip');box.replaceChildren(make('strong',node.data('title')),make('small',[...(node.data('authors')||[]),node.data('year'),pinned.has(node.id())?'已固定 · 可再次拖动':'点击查看 · 双击阅读'].filter(Boolean).join(' · ')));box.hidden=false;const p=node.renderedPosition(),width=el('literature-graph').clientWidth;box.style.left=Math.max(8,Math.min(width-315,p.x+18))+'px';box.style.top=Math.max(8,Math.min(el('literature-graph').clientHeight-110,p.y-40))+'px';}
  function ensureCanvas(){if(cy)return;cy=cytoscape({container:el('literature-graph'),elements:[],style:styles(),layout:{name:'preset'},minZoom:.12,maxZoom:2.7,boxSelectionEnabled:false,selectionType:'single'});
    cy.on('tap','node',event=>{fitWhenSettled=false;if(cameraTimer)clearTimeout(cameraTimer);const n=data.nodes.find(n=>n.id===event.target.id());if(!n)return;const now=performance.now();if(lastTap.id===n.id&&now-lastTap.time<330&&n.current){window.openPaper(n.id,n.title);lastTap={id:'',time:0};}else{detail(n);cameraTimer=setTimeout(()=>{if(selected===n.id&&!dragging.has(n.id))camera(n.id);},340);lastTap={id:n.id,time:now};}});

    cy.on('tap','edge',event=>{const edge=data.edges.find(e=>C.edgeKey(e)===event.target.data('key'));if(edge)detailEdge(edge);});cy.on('tap',event=>{if(event.target===cy)clearSelection();});
    cy.on('mouseover','node',event=>{highlight(event.target.id(),true);tooltip(event.target);});
    cy.on('mouseout','node',()=>{el('graph-tooltip').hidden=true;cy.elements().removeClass('dimmed hovered');if(selected)highlight(selected);});
    cy.on('mousedown touchstart scrollzoom',()=>{fitWhenSettled=false;});
    cy.on('grab','node',event=>{if(cameraTimer)clearTimeout(cameraTimer);dragging.add(event.target.id());event.target.stop();simulate();});
    cy.on('drag','node',event=>{dragged.add(event.target.id());tooltip(event.target);});
    cy.on('free','node',event=>{dragging.delete(event.target.id());if(dragged.has(event.target.id())){pinned.add(event.target.id());event.target.addClass('pinned');dragged.delete(event.target.id());}pinControl();el('graph-tooltip').hidden=true;if(selected===event.target.id())detail(data.nodes.find(n=>n.id===selected));simulate();});
    cy.on('pan zoom position add remove',scheduleMap);
  }
  function render(incoming,replace=false,anchor=''){
    ensureCanvas();clearMotion();el('graph-find-results').hidden=true;el('graph-find-results').replaceChildren();const oldPositions=new Map(cy.nodes().map(n=>[n.id(),{...n.position()}]));data=C.merge(replace?null:data,incoming).data;
    const groups=C.groups(data),palette=colors(),nodeColors=new Map(),degree=new Map(data.nodes.map(n=>[n.id,new Set()]));
    groups.forEach((group,i)=>group.forEach(id=>nodeColors.set(id,palette[i%palette.length])));for(const edge of data.edges){degree.get(edge.source)?.add(edge.target);degree.get(edge.target)?.add(edge.source);}
    if(replace)cy.elements().remove();cy.nodes().removeClass('fresh');if(freshTimer)clearTimeout(freshTimer);const wanted=new Set(data.nodes.map(n=>n.id)),edgeIds=new Set(data.edges.map(e=>'graph-edge:'+encodeURIComponent(C.edgeKey(e))));
    cy.batch(()=>{
      cy.nodes().filter(n=>!wanted.has(n.id())).remove();cy.edges().filter(e=>!edgeIds.has(e.id())).remove();
      data.nodes.forEach((node,i)=>{const label=(el('graph-layout').value==='timeline'?C.timelineLabel(node)+' · ':'')+(node.title.length>25?node.title.slice(0,24)+'…':node.title),values={...node,label,color:nodeColors.get(node.id),degree:degree.get(node.id)?.size||0,size:10+Math.min(12,Math.sqrt(degree.get(node.id)?.size||0)*2.3),renderSize:16,fontSize:12,labelWidth:144,labelGap:7};
        let element=cy.getElementById(node.id);if(!element.length){const center=oldPositions.get(anchor)||{x:0,y:0},a=i*2.399;cy.add({group:'nodes',data:values,position:oldPositions.get(node.id)||{x:center.x+Math.cos(a)*130,y:center.y+Math.sin(a)*130}});element=cy.getElementById(node.id);if(anchor)element.addClass('fresh');}else element.data(values);
        element.toggleClass('center',node.id===seed).toggleClass('missing',!node.current).toggleClass('pinned',pinned.has(node.id));
      });
      data.edges.forEach(edge=>{const key=C.edgeKey(edge),id='graph-edge:'+encodeURIComponent(key),values={...edge,id,key};const element=cy.getElementById(id);if(element.length)element.data(values);else cy.add({group:'edges',data:values});});
    });pinControl();filters();if(anchor)freshTimer=setTimeout(()=>cy?.nodes().removeClass('fresh'),1800);if(selected&&data.nodes.some(n=>n.id===selected))detail(data.nodes.find(n=>n.id===selected));else clearSelection();
  }
  function syncMotionControl(){const allowed=isMoving()&&el('graph-layout').value==='network';el('graph-motion').disabled=!allowed;el('graph-motion').title=!isMoving()?'当前已关闭或减少动画':'动态网络支持受力舒展';}
  function arrange(shouldFit=true){
    if(!cy||!data)return;clearMotion();cy.resize();fitWhenSettled=shouldFit;const version=layoutVersion,view=visibleData(),targets=C.positions(view,el('graph-layout').value,seed||selected);
    const timeline=el('graph-layout').value==='timeline';cy.nodes().forEach(n=>n.data('label',(timeline?C.timelineLabel(n.data())+' · ':'')+(n.data('title').length>25?n.data('title').slice(0,24)+'…':n.data('title'))));syncMotionControl();
    layoutJob=cy.elements().not('.filtered').layout({name:'preset',positions:n=>pinned.has(n.id())?n.position():targets[n.id()]||n.position(),fit:shouldFit,padding:55,animate:isMoving(),animationDuration:480,stop:()=>{if(version!==layoutVersion)return;layoutJob=null;if(el('graph-layout').value==='network')simulate();else activity((timeline?'按年份从左至右排列':'同心布局已就绪')+(pinned.size?' · 固定位置保留':''));}});layoutJob.run();
  }
  async function load(target={seed,query:currentQuery}){
    const options={limit:el('graph-limit').value,auto:el('graph-auto').checked,archived:el('graph-archived').checked};
    const incoming=await request('/api/graph',{query:target.seed?'':target.query,seed:target.seed,limit:Number(options.limit),include_auto:options.auto,include_archived:options.archived});if(!incoming)return;
    checkpoint();savedStamp='';applied=options;seed=target.seed;currentQuery=target.query;selected=seed;pinned=new Set();render(incoming,true);arrange();historyButtons();
  }
  async function expandNode(id){
    if(busy||!data)return;if(data.nodes.length>=80){el('graph-summary').textContent='已达80篇上限，可选“以此为中心”继续探索。';return;}
    fitWhenSettled=false;const incoming=await request('/api/graph/expand',{seed:id,known_ids:data.nodes.map(n=>n.id),limit:8,include_auto:el('graph-auto').checked,include_archived:el('graph-archived').checked});if(!incoming)return;
    if(!incoming.added_ids.length){el('graph-summary').textContent='该文献在当前来源范围内没有更多未展示的关联；可切换来源或建立人工关系。';activity('视图保持原位');detail(data.nodes.find(n=>n.id===id));return;}
    checkpoint();selected=id;render(incoming,false,id);if(el('graph-layout').value==='network')simulate();else arrange(false);el('graph-summary').textContent+=` · 本次展开 ${incoming.added_ids.length} 篇`;
  }
  function syncListSelection(){el('graph-paper-list').querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.id===selected)));}
  function renderList(){const box=el('graph-paper-list');box.replaceChildren();for(const node of visibleData().nodes){const b=make('button',node.title,'graph-list-item');b.dataset.id=node.id;b.setAttribute('aria-pressed',String(node.id===selected));b.onclick=()=>{detail(node);camera(node.id);el('literature-graph').scrollIntoView({block:'nearest',behavior:isMoving()?'smooth':'instant'});};box.append(b);}}
  function readableLabels(){
    if(!cy||!data)return;const adaptive=el('graph-label-mode').value==='adaptive',z=cy.zoom(),scale=Math.max(.35,Math.min(1,z));
    cy.batch(()=>cy.nodes().forEach(n=>n.data({renderSize:n.data('size')*Number(el('graph-node-scale').value)/100/scale,fontSize:12/scale,labelWidth:144/scale,labelGap:7/scale})));
    const nodes=cy.nodes().not('.filtered').map(n=>{const p=n.renderedPosition(),text=n.data('label'),units=Array.from(text).reduce((sum,ch)=>sum+(ch.charCodeAt(0)>255?1:.55),0),radius=n.data('renderSize')*z/2;return {id:n.id(),x:p.x+radius+7*z/scale,y:p.y-8*z/scale,width:Math.min(144,units*12)*z/scale,height:16*z/scale,priority:n.id()===selected?1e6:n.data('degree')||0,dot:{x:p.x,y:p.y,r:radius+3}};});
    const ids=new Set(adaptive?C.labelIds(nodes,z):nodes.map(n=>n.id));cy.nodes().forEach(n=>n.toggleClass('labels-hidden',!ids.has(n.id())));
  }
  function scheduleMap(){if(minimapTimer)return;minimapTimer=setTimeout(()=>{minimapTimer=0;readableLabels();drawMap();},100);}
  function drawMap(){
    if(!cy||!data||!el('graph-minimap-visible').checked)return;const nodes=cy.nodes().not('.filtered'),svg=el('graph-minimap').querySelector('svg');svg.replaceChildren();if(!nodes.length)return;
    const box=nodes.boundingBox({includeLabels:false}),scale=Math.min(160/Math.max(1,box.w+70),86/Math.max(1,box.h+70)),offset={x:10+(160-(box.w+70)*scale)/2,y:6+(86-(box.h+70)*scale)/2};mapTransform={scale,x:box.x1-35,y:box.y1-35,offset};
    const shape=(tag,attrs)=>{const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,String(v));svg.append(n);return n;},point=p=>({x:offset.x+(p.x-mapTransform.x)*scale,y:offset.y+(p.y-mapTransform.y)*scale});
    cy.edges().not('.filtered').forEach(e=>{const a=point(e.source().position()),b=point(e.target().position());shape('line',{x1:a.x,y1:a.y,x2:b.x,y2:b.y,stroke:'var(--muted)','stroke-width':.5,opacity:.35});});
    nodes.forEach(n=>{const p=point(n.position());shape('circle',{cx:p.x,cy:p.y,r:n.id()===selected?3:2,fill:n.data('color')});});
    const extent=cy.extent(),a=point({x:extent.x1,y:extent.y1});shape('rect',{x:a.x,y:a.y,width:extent.w*scale,height:extent.h*scale,fill:'none',stroke:'var(--accent)','stroke-width':1.1,rx:2});
  }
  el('graph-minimap').onclick=event=>{fitWhenSettled=false;if(!mapTransform||event.detail===0){fit();return;}const rect=el('graph-minimap').querySelector('svg').getBoundingClientRect(),x=(event.clientX-rect.left)*180/rect.width,y=(event.clientY-rect.top)*110/rect.height,p={x:(x-mapTransform.offset.x)/mapTransform.scale+mapTransform.x,y:(y-mapTransform.offset.y)/mapTransform.scale+mapTransform.y};cy.stop();const pan={x:cy.width()/2-p.x*cy.zoom(),y:cy.height()/2-p.y*cy.zoom()};if(isMoving())cy.animate({pan},{duration:240});else cy.pan(pan);};
  el('graph-form').onsubmit=event=>{event.preventDefault();load({seed:'',query:el('graph-query').value.trim()});};
  el('graph-overview').onclick=()=>{el('graph-query').value='';load({seed:'',query:''});};
  el('graph-back').onclick=()=>historyMove(true);el('graph-forward').onclick=()=>historyMove(false);
  el('graph-reset').onclick=fit;el('graph-rearrange').onclick=()=>arrange();el('graph-layout').onchange=()=>arrange();
  el('graph-unpin').onclick=()=>{pinned.clear();pinControl();cy?.nodes().removeClass('pinned');if(selected)detail(data.nodes.find(n=>n.id===selected));simulate();};
  el('graph-motion').onclick=()=>{motion=!motion;el('graph-motion').setAttribute('aria-pressed',String(motion));el('graph-motion').textContent='动态布局：'+(motion?'开':'关');if(motion)simulate();else stopSimulation('动态已暂停');};
  for(const key of ['in','out'])el('graph-zoom-'+key).onclick=()=>{fitWhenSettled=false;if(!cy)return;const old=cy.zoom(),z=Math.max(.12,Math.min(2.7,old*(key==='in'?1.22:1/1.22))),p=cy.pan(),cx=cy.width()/2,cyy=cy.height()/2;const pan={x:cx-(cx-p.x)*z/old,y:cyy-(cyy-p.y)*z/old};cy.stop();if(isMoving())cy.animate({zoom:z,pan},{duration:180});else{cy.zoom(z);cy.pan(pan);}};
  document.querySelectorAll('[data-graph-origin]').forEach(button=>button.onclick=()=>{origin=button.dataset.graphOrigin;filters();if(selected)detail(data.nodes.find(n=>n.id===selected));simulate();});
  for(const id of ['graph-auto','graph-archived','graph-limit'])el(id).addEventListener('change',()=>load());
  for(const id of ['graph-orphans','graph-labels','graph-minimap-visible'])el(id).addEventListener('change',()=>{if(data){filters();simulate();}});
  el('graph-spacing').oninput=()=>simulate();
  el('graph-node-scale').oninput=()=>{if(cy){cy.style(styles());scheduleMap();}};
  el('graph-label-mode').onchange=()=>scheduleMap();
  el('graph-find').oninput=()=>{const q=el('graph-find').value.trim().toLocaleLowerCase(),box=el('graph-find-results');box.replaceChildren();box.hidden=!q;if(!q||!data)return;const found=visibleData().nodes.filter(n=>[n.title,...(n.authors||[]),...(n.tags||[])].join(' ').toLocaleLowerCase().includes(q));for(const n of found.slice(0,12)){const b=make('button',n.title);b.onclick=()=>{detail(n);camera(n.id);box.hidden=true;};box.append(b);}if(!found.length)box.append(make('p','当前可见图中没有匹配文献。'));};
  function immersive(value,remember=true){if(remember)immersivePreferred=value;document.body.classList.toggle('graph-immersive',value);el('graph-immersive').setAttribute('aria-pressed',String(value));el('graph-immersive').textContent=value?'退出沉浸':'沉浸探索';requestAnimationFrame(()=>cy?.resize());}
  el('graph-immersive').onclick=()=>immersive(!document.body.classList.contains('graph-immersive'));
  document.addEventListener('keydown',event=>{if(event.key==='Escape'){if(document.body.classList.contains('graph-immersive'))immersive(false);el('graph-find-results').hidden=true;el('graph-tooltip').hidden=true;}});
  el('literature-graph').onkeydown=event=>{if(!cy)return;if(['+','=','-'].includes(event.key)){event.preventDefault();el(event.key==='-'?'graph-zoom-out':'graph-zoom-in').click();}const delta={ArrowLeft:[40,0],ArrowRight:[-40,0],ArrowUp:[0,40],ArrowDown:[0,-40]}[event.key];if(delta){event.preventDefault();cy.panBy({x:delta[0],y:delta[1]});}if(event.key==='Escape')clearSelection();};
  new ResizeObserver(()=>{if(cy&&!el('graph-view').hidden){cy.resize();scheduleMap();}}).observe(el('literature-graph'));
  new MutationObserver(()=>{if(cy){const palette=colors();C.groups(data||{nodes:[],edges:[]}).forEach((group,i)=>group.forEach(id=>cy.getElementById(id).data('color',palette[i%palette.length])));cy.style(styles());cy.resize();scheduleMap();syncMotionControl();if(!isMoving())clearMotion();}}).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme','data-design','data-density','data-motion']});
  reduced.addEventListener('change',()=>{syncMotionControl();if(!isMoving())clearMotion();});document.addEventListener('visibilitychange',()=>{if(document.hidden)clearMotion();});
  document.addEventListener('workspaceview',event=>{if(event.detail==='graph-view'){if(immersivePreferred)immersive(true,false);if(!data&&!opening)load({seed:'',query:''});else requestAnimationFrame(()=>cy?.resize());}else{clearMotion();el('graph-tooltip').hidden=true;if(document.body.classList.contains('graph-immersive'))immersive(false,false);}});
  window.captureGraphView=()=>{if(!data||busy||writing)throw Error('请等待图谱载入后再保存。');const r=record();return {...r,ids:data.nodes.map(n=>n.id),node_scale:Number(el('graph-node-scale').value),label_mode:el('graph-label-mode').value};};
  window.restoreGraphView=view=>{if(busy||writing||linkDirty)throw Error('请先处理正在进行的操作或未保存关系。');ensureCanvas();checkpoint();clearMotion();const s=view.state;savedStamp=view.updated.slice(0,10);seed=s.seed;currentQuery=s.query;selected=s.selected;pinned=new Set(s.pinned);origin=s.origin;el('graph-layout').value=s.layout;el('graph-orphans').checked=s.orphans;el('graph-query').value=s.query;el('graph-limit').value=['15','30','50','80'].includes(s.limit)?s.limit:'80';el('graph-auto').checked=s.auto;el('graph-archived').checked=s.archived;el('graph-node-scale').value=s.node_scale;el('graph-label-mode').value=s.label_mode;applied={limit:el('graph-limit').value,auto:s.auto,archived:s.archived};render(view.data,true);cy.nodes().forEach(n=>{if(s.positions[n.id()])n.position(s.positions[n.id()]);});cy.zoom(s.viewport.zoom);cy.pan(s.viewport.pan);activity('已恢复保存位置 · 关系为快照');syncMotionControl();historyButtons();};
  window.openLiteratureGraph=id=>{opening=true;showView('graph-view');opening=false;load({seed:id,query:''});};
  window.enhanceGraphResult=(box,source)=>{const b=make('button','查看文献关联','text-button');b.onclick=()=>window.openLiteratureGraph(source.item_id);box.append(b);};
  async function lookup(){try{const response=await fetch('/api/literature/catalog?query='+encodeURIComponent(el('graph-link-query').value),{headers:{'X-Sociolit-Token':token}});if(!response.ok)throw Error('查找文献失败');const values=await response.json();for(const key of ['graph-link-source','graph-link-target']){const previous=el(key).value, keep=Array.from(el(key).options).find(o=>o.value===previous);el(key).replaceChildren();const merged=new Map(values.map(v=>[v.id,v.title]));if(keep)merged.set(keep.value,keep.textContent);for(const [id,title] of merged){const option=document.createElement('option');option.value=id;option.textContent=title;el(key).append(option);}if(keep)el(key).value=previous;else if(key==='graph-link-target'&&values.length>1)el(key).selectedIndex=1;}el('graph-link-hint').textContent=`找到 ${values.length} 篇，最多显示30篇。选择两篇并说明关系；可继续查找另一题名，已选项会保留。`;}catch(error){notice(error.message,true);}}
  el('graph-link-lookup').onclick=lookup;el('graph-link-reset').onclick=()=>{el('graph-link-form').reset();linkDirty=false;notice('已清空未保存关系输入。');};
  el('graph-link-form').onsubmit=async event=>{event.preventDefault();try{await mutateLink('/api/graph/links',{source:el('graph-link-source').value,target:el('graph-link-target').value,kind:el('graph-link-kind').value,note:el('graph-link-note').value});await load({seed:el('graph-link-source').value,query:''});linkDirty=false;notice('关系已保存到本机。');}catch(error){notice(error.message,true);}};


})();
