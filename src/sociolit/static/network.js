/* Local, pinned Cytoscape.js renderer. All graph data stays on loopback. */
(() => {
  let data=null, seed='', selected='', busy=false, writing=false, linkDirty=false, cy=null;
  const make=(tag,text='',cls='')=>{const n=document.createElement(tag);n.textContent=text;n.className=cls;return n;};
  window.isGraphBusy=()=>busy||writing;window.isGraphDirty=()=>linkDirty;
  el('graph-link-form').addEventListener('input',()=>{linkDirty=true;});
  async function mutateLink(path,payload){writing=true;try{return await api(path,payload);}finally{writing=false;}}
  function styles(){const s=getComputedStyle(document.documentElement),c=name=>s.getPropertyValue('--'+name).trim(),n=(name,fallback)=>parseFloat(c(name))||fallback;return [
    {selector:'node',style:{'shape':c('graph-node-shape')||'ellipse','width':n('graph-node-width',24),'height':n('graph-node-height',24),'background-color':c('surface'),'border-width':2,'border-color':c('accent'),'label':'data(label)','font-size':n('graph-label-size',12),'font-family':c('ui-font')||'Segoe UI, Microsoft YaHei, sans-serif','color':c('text'),'text-valign':'bottom','text-margin-y':9,'text-halign':'center','text-wrap':'wrap','text-max-width':96,'text-overflow-wrap':'anywhere','text-outline-color':c('soft'),'text-outline-width':2,'padding':3,'overlay-opacity':0}},
    {selector:'node.center',style:{'background-color':c('accent'),'color':c('accent-text'),'width':n('graph-node-width',24)*1.4,'height':n('graph-node-height',24)*1.4,'border-color':c('accent'),'border-width':2,'font-weight':600}},
    {selector:'node.missing',style:{'border-style':'dashed','opacity':.6}},
    {selector:'edge',style:{'width':n('graph-edge-width',1.2),'line-color':c('muted'),'opacity':.25,'curve-style':'bezier','line-style':'dashed','overlay-opacity':0}},
    {selector:'edge[origin="manual"]',style:{'line-color':c('accent'),'opacity':.7,'width':2,'line-style':'solid'}},
    {selector:'edge[kind="cites"]',style:{'target-arrow-shape':'triangle','target-arrow-color':c('accent')}},
    {selector:'edge[origin="comparison"]',style:{'line-color':'#9774bd','line-style':'dotted','opacity':.55}},
    {selector:'edge[origin="semantic"]',style:{'line-color':'#54a69a','opacity':.45}},
    {selector:'.dimmed',style:{'opacity':.12}},
    {selector:'node.focused',style:{'border-width':2.5,'border-color':c('accent'),'font-weight':600}},
    {selector:'edge.focused',style:{'opacity':.8,'width':2,'line-color':c('accent')}},
    {selector:'node:selected',style:{'border-color':c('accent'),'border-width':3}}
  ];}
  function fit(){if(cy){cy.resize();cy.fit(undefined,45);}}
  function layout(){
    if(!cy)return;cy.resize();cy.elements().removeClass('dimmed focused');
    cy.layout(el('graph-layout').value==='concentric'?{name:'concentric',animate:false,padding:35,minNodeSpacing:20,avoidOverlap:true,nodeDimensionsIncludeLabels:true,concentric:n=>seed?(n.id()===seed?2:1):n.degree(),levelWidth:()=>seed?.5:2}:
      {name:'cose',animate:false,randomize:false,padding:45,nodeDimensionsIncludeLabels:true,nodeRepulsion:()=>2048,idealEdgeLength:()=>70,edgeElasticity:()=>32,nodeOverlap:20,componentSpacing:80,numIter:900,initialTemp:160,coolingFactor:.95,minTemp:1}).run();
    if(cy.zoom()<.8){cy.zoom(.8);cy.center(seed?cy.getElementById(seed):cy.elements());}
    if(selected){const node=data.nodes.find(n=>n.id===selected);if(node)detail(node);}
  }
  function detail(node){
    selected=node.id;const panel=el('graph-detail');panel.replaceChildren(make('h3',node.title),make('p',[(node.authors||[]).join('、'),node.year,node.current?'':'保留的书目快照'].filter(Boolean).join(' · ')));
    const neighbors=data.edges.filter(e=>e.source===node.id||e.target===node.id);panel.append(make('span',`${neighbors.length} 条关联线索`,'graph-node-count'));
    if(node.current){const actions=make('div','','toolbar');const focus=make('button','以此为中心','secondary');focus.onclick=()=>{seed=node.id;load();};const read=make('button','摘要与原文','secondary');read.onclick=()=>window.openPaper(node.id,node.title);actions.append(focus,read);panel.append(actions);}
    for(const edge of neighbors){const row=make('article','','graph-relation'),other=data.nodes.find(n=>n.id===(edge.source===node.id?edge.target:edge.source));const title=make('button',other?.title||'未知文献','text-button');title.onclick=()=>{if(other)detail(other);};
      row.append(make('p',(edge.kind==='cites'&&edge.target===node.id?'被引用（本人确认）':edge.label)+(edge.note?' · '+edge.note:'')),title);
      if(edge.origin==='manual'){const archive=make('button',edge.archived?'恢复关系':'归档关系','secondary');archive.onclick=async()=>{try{await mutateLink('/api/graph/links/archive',{identity:edge.id,revision:edge.revision,archived:!edge.archived});await load();}catch(error){notice(error.message,true);}};row.append(archive);}panel.append(row);}
    if(!neighbors.length)panel.append(make('p','本视图尚无关联；可在下方手动连接文献。'));
    if(cy){cy.elements().removeClass('dimmed focused');const focus=cy.getElementById(node.id);cy.elements().not(focus.closedNeighborhood()).addClass('dimmed');focus.closedNeighborhood().addClass('focused');focus.select();cy.nodes().not(focus).unselect();}
    el('graph-paper-list').querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.id===selected)));
  }
  function draw(){
    if(cy)cy.destroy();const elements=[...data.nodes.map((node,i)=>({data:{...node,label:node.title.length>20?node.title.slice(0,19)+'…':node.title},classes:[node.id===seed?'center':'',node.current?'':'missing'].join(' '),position:{x:(i%6)*180,y:Math.floor(i/6)*130}})),...data.edges.map((edge,i)=>({data:{...edge,id:'edge-'+i}}))];
    cy=cytoscape({container:el('literature-graph'),elements,style:styles(),layout:{name:'preset'},minZoom:.18,maxZoom:2.3,boxSelectionEnabled:false,selectionType:'single'});
    cy.on('tap','node',event=>{const node=data.nodes.find(n=>n.id===event.target.id());if(node)detail(node);});
    cy.on('tap',event=>{if(event.target===cy){cy.elements().removeClass('dimmed focused');cy.nodes().unselect();selected='';el('graph-detail').replaceChildren(make('h3','探索文献之间的联系'),make('p','点击节点，查看关联理由；使用“摘要与原文”回到文献。'));}});
    cy.on('tap','edge',event=>{const edge=event.target.data();notice(edge.label+(edge.note?' · '+edge.note:''));});
    el('graph-paper-list').replaceChildren();for(const node of data.nodes){const b=make('button',node.title,'graph-list-item');b.dataset.id=node.id;b.setAttribute('aria-pressed','false');b.onclick=()=>{detail(node);cy.fit(cy.getElementById(node.id).closedNeighborhood(),65);};el('graph-paper-list').append(b);}
    layout();if(!selected)el('graph-detail').replaceChildren(make('h3','探索文献之间的联系'),make('p','点击一篇文献，它的关联会突出显示。线索类型与理由显示在这里。'));if(seed){const node=data.nodes.find(n=>n.id===seed);if(node)detail(node);}
  }
  async function load(){
    if(busy)return;busy=true;el('graph-load').disabled=true;
    try{data=await api('/api/graph',{query:seed?'':el('graph-query').value.trim(),seed,limit:Number(el('graph-limit').value),include_auto:el('graph-auto').checked,include_archived:el('graph-archived').checked});if(!data.nodes.some(n=>n.id===selected))selected='';draw();el('graph-summary').textContent=`${data.nodes.length} 篇文献 · ${data.edges.length} 条关系${data.limited?' · 可缩小主题查看更多相关文献':''}。${data.message}`;if(!data.nodes.length)el('graph-detail').textContent='暂未找到匹配书目，请更换主题关键词。';}catch(error){notice(error.message,true);}finally{busy=false;el('graph-load').disabled=false;}
  }
  window.openLiteratureGraph=id=>{seed=id;selected=id;showView('graph-view');load();};
  window.enhanceGraphResult=(box,source)=>{const b=make('button','查看文献关联','text-button');b.onclick=()=>window.openLiteratureGraph(source.item_id);box.append(b);};
  el('graph-form').onsubmit=event=>{event.preventDefault();seed='';selected='';load();};el('graph-reset').onclick=fit;el('graph-rearrange').onclick=layout;el('graph-layout').onchange=layout;
  el('graph-zoom-in').onclick=()=>cy?.zoom({level:Math.min(2.3,cy.zoom()*1.2),renderedPosition:{x:cy.width()/2,y:cy.height()/2}});
  el('graph-zoom-out').onclick=()=>cy?.zoom({level:Math.max(.18,cy.zoom()/1.2),renderedPosition:{x:cy.width()/2,y:cy.height()/2}});
  for(const id of ['graph-auto','graph-archived','graph-limit'])el(id).addEventListener('change',()=>load());
  new ResizeObserver(()=>{if(cy&&!el('graph-view').hidden)cy.resize();}).observe(el('literature-graph'));
  new MutationObserver(()=>{if(cy){cy.style(styles());cy.resize();}}).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme','data-design','data-density']});
  document.addEventListener('workspaceview',event=>{if(event.detail==='graph-view'){if(!data)load();else requestAnimationFrame(()=>cy?.resize());}});
  el('literature-graph').onkeydown=event=>{if(!cy)return;if(event.key==='Escape'){cy.elements().removeClass('dimmed focused');cy.nodes().unselect();}if(event.key==='+'||event.key==='=')el('graph-zoom-in').click();if(event.key==='-')el('graph-zoom-out').click();};
  async function lookup(){try{const response=await fetch('/api/literature/catalog?query='+encodeURIComponent(el('graph-link-query').value),{headers:{'X-Sociolit-Token':token}});if(!response.ok)throw Error('查找文献失败');const values=await response.json();for(const key of ['graph-link-source','graph-link-target']){const previous=el(key).value, keep=Array.from(el(key).options).find(o=>o.value===previous);el(key).replaceChildren();const merged=new Map(values.map(v=>[v.id,v.title]));if(keep)merged.set(keep.value,keep.textContent);for(const [id,title] of merged){const option=document.createElement('option');option.value=id;option.textContent=title;el(key).append(option);}if(keep)el(key).value=previous;else if(key==='graph-link-target'&&values.length>1)el(key).selectedIndex=1;}el('graph-link-hint').textContent=`找到 ${values.length} 篇，最多显示30篇。选择两篇并说明关系；可继续查找另一题名，已选项会保留。`;}catch(error){notice(error.message,true);}}
  el('graph-link-lookup').onclick=lookup;el('graph-link-reset').onclick=()=>{el('graph-link-form').reset();linkDirty=false;notice('已清空未保存关系输入。');};
  el('graph-link-form').onsubmit=async event=>{event.preventDefault();try{await mutateLink('/api/graph/links',{source:el('graph-link-source').value,target:el('graph-link-target').value,kind:el('graph-link-kind').value,note:el('graph-link-note').value});seed=el('graph-link-source').value;await load();linkDirty=false;notice('关系已保存到本机。');}catch(error){notice(error.message,true);}};

})();
