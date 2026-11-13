(() => {
  const basket = new Map();
  let board = null, dirty = false, busy = false, exporting = false, seed = null, excerptItem = null;
  let preview = null, candidate = null, annotationOffset = 0, annotationTotal = 0, annotationShown = 0;
  window.isLiteratureBusy = () => busy || exporting;
  window.isLiteratureDirty = () => dirty || basket.size > 0 || Boolean(candidate);
  const kinds = {pdf:'PDF 原文',ocr:'OCR（需核对）',metadata:'书目信息',note:'个人笔记',annotation:'Zotero 摘录与个人批注'};
  const fields = {question:'研究问题',theory:'理论视角',data:'数据与对象',methods:'研究方法',findings:'主要发现',limits:'局限与适用范围'};
  function element(tag, text, className='') {const node=document.createElement(tag); node.textContent=text;
    if(className)node.className=className;return node;}
  async function read(path) {const response=await fetch(path,{headers:{'X-Sociolit-Token':token}});
    const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'读取失败');return data;}
  function invalidate() {preview=null;el('compare-preview').hidden=true;el('compare-consent').checked=false;}
  function changed() {dirty=true;invalidate();el('compare-save-state').textContent='有未保存修改，请先保存再切换、导出或生成 AI 草稿。';}
  async function working(action) {if(busy||exporting)return;busy=true;
    const buttons=[...document.querySelectorAll('#literature-view button,#annotations-view button')].filter(node=>!node.disabled);
    buttons.forEach(node=>{node.disabled=true;});
    try {await action();} catch(error){notice(error.message,true);}
    finally {busy=false;buttons.forEach(node=>{node.disabled=false;});pagination();}}
  function pagination(){el('annotations-prev').disabled=annotationOffset===0;
    el('annotations-next').disabled=annotationOffset+annotationShown>=annotationTotal;}
  function keepEdits() {if(dirty){notice('请先保存当前对照表的修改，再进行这项操作。',true);return false;}return true;}
  function add(row) {
    if(busy)return;
    if(basket.has(row.id)) {notice('这个片段已经在对照篮中。');return;}
    if(basket.size>=8 || (new Set([...basket.values()].map(source=>source.item_id)).size>=6 &&
      ![...basket.values()].some(source=>source.item_id===row.item_id))) {notice('每张表最多 6 篇文献、合计 8 个片段。',true);return;}
    basket.set(row.id,row);renderBasket();notice('片段已加入对照篮；可继续选另一篇文献，再到“推荐与比较”创建表。');
  }
  window.enhanceLiteratureResult=(box,row)=>{
    const toolbar=element('div','', 'toolbar literature-actions');
    const similar=element('button','相似文献','secondary');similar.onclick=()=>working(()=>loadRecommendations(row.item_id));
    const compare=element('button','加入文献对照','secondary');compare.onclick=()=>add(row);
    toolbar.append(similar,compare);box.append(toolbar);
  };
  function renderBasket() {el('comparison-basket').replaceChildren();
    el('comparison-count').textContent=`已选 ${new Set([...basket.values()].map(source=>source.item_id)).size} 篇文献、${basket.size} / 8 个片段。`;
    for(const [id,row] of basket){const line=element('div','', 'ai-selection');
      line.append(element('span',row.title+(row.page?` · PDF 第 ${row.page} 页`:' · '+(kinds[row.kind]||row.kind))));
      const remove=element('button','移除','text-button');remove.onclick=()=>{basket.delete(id);renderBasket();};line.append(remove);el('comparison-basket').append(line);}}
  el('comparison-clear').onclick=()=>{basket.clear();renderBasket();};
  async function loadRecommendations(identity) {seed=identity;showView('literature-view');
    await loadBoards();
    if(board)await loadConnections();
    notice('正在本机查找相似文献…');
    const result=await api('/api/literature/recommend',{item_id:identity,mode:el('recommend-mode').value});
    el('recommend-seed').textContent='参考文献：'+result.seed.title;
    el('recommend-message').textContent=result.message+' 范围：'+result.scope;
    el('recommend-results').replaceChildren();
    for(const item of result.results){const box=element('article','', 'result');box.append(element('h3',item.title));
      box.append(element('small',[(item.authors||[]).join('、'),item.year,item.journal].filter(Boolean).join(' · ')));
      box.append(element('p',(item.reasons||[]).join('；'),'hint'));
      if(item.excerpt)box.append(element('pre',item.excerpt));
      const button=element('button','查看片段并加入对照','secondary');button.onclick=()=>working(()=>loadExcerpts(item.id));box.append(button);
      const related=element('button','以此文献继续推荐','secondary');related.onclick=()=>working(()=>loadRecommendations(item.id));box.append(related);
      el('recommend-results').append(box);}
    if(!result.results.length)el('recommend-results').textContent='暂未找到足够接近的候选。可补充摘要、标签，或尝试已有语义索引。';
    notice('推荐已完成；它是本机检索线索，请核对文献内容。');
  }
  el('recommend-refresh').onclick=()=>{if(seed)working(()=>loadRecommendations(seed));else notice('先在检索结果点击“相似文献”。');};
  el('recommend-mode').onchange=()=>{if(seed)working(()=>loadRecommendations(seed));};
  async function loadExcerpts(identity,query=''){excerptItem=identity;showView('literature-view');
    const result=await api('/api/literature/excerpts',{item_id:identity,query});
    el('literature-excerpts').hidden=false;el('literature-excerpt-title').textContent=result.item.title;
    el('literature-chunks').replaceChildren();
    for(const row of result.chunks){const box=element('article','', 'result');box.append(element('small',
      (kinds[row.kind]||row.kind)+(row.page?` · PDF 第 ${row.page} 页 · 文件标签 ${row.page_label||'未提供'}`:'')));
      box.append(element('pre',row.text));if(row.pdf_url){const link=element('a','回到原文对应页 ↗');link.href=row.pdf_url;link.target='_blank';link.rel='noopener';box.append(link);}
      const button=element('button','加入文献对照','secondary');button.onclick=()=>add(row);box.append(button);
      if(window.enhanceAIResult)window.enhanceAIResult(box,row);el('literature-chunks').append(box);}
    if(!result.chunks.length)el('literature-chunks').textContent='本篇未找到匹配片段。';}
  el('literature-excerpt-search').onsubmit=event=>{event.preventDefault();if(excerptItem)working(()=>loadExcerpts(excerptItem,el('literature-within-query').value));};
  async function loadBoards(keep=''){const selected=keep||el('comparison-list').value;
    const rows=await read('/api/comparisons?include_archived='+el('comparison-include-archived').checked);
    el('comparison-list').replaceChildren();for(const row of rows){const option=element('option',row.title+(row.archived?'（已归档）':''));option.value=row.id;el('comparison-list').append(option);}
    if(rows.some(row=>row.id===selected))el('comparison-list').value=selected;
    if(!rows.length)el('comparison-list').append(element('option','尚无已保存对照表'));}
  async function openBoard(identity){if(!identity)return;board=await read('/api/comparisons/'+encodeURIComponent(identity));
    dirty=false;candidate=null;el('compare-ai-result').hidden=true;invalidate();
    el('comparison-editor').hidden=false;el('comparison-title').value=board.title;
    el('compare-save-state').textContent=(board.origin==='ai_draft'?'AI 草稿，逐格人工核对后再使用。':'人工对照表。')+' 已保存，来源是创建时的片段快照。';
    el('comparison-archive').textContent=board.archived?'恢复对照表':'归档对照表';renderMatrix(el('comparison-matrix'),board,true);
    renderSources(el('comparison-sources'),board.sources);await loadConnections();}
  el('comparison-open').onclick=()=>{if(keepEdits())working(()=>openBoard(el('comparison-list').value));};
  el('comparison-include-archived').onchange=()=>working(()=>loadBoards());
  el('comparison-new').onclick=()=>{if(!keepEdits())return;working(async()=>{
    const result=await api('/api/comparisons',{title:el('comparison-new-title').value,
      sources:[...basket.values()].map(row=>({chunk_id:row.id,digest:row.source_digest}))});
    basket.clear();renderBasket();await loadBoards(result.id);await openBoard(result.id);notice('对照表已创建并保存；六个维度等待填写与核对。');});};
  function renderMatrix(container,data,editable){container.replaceChildren();const table=document.createElement('table');table.className='comparison-table';
    const head=document.createElement('thead'),headers=document.createElement('tr');headers.append(element('th','比较维度'));
    for(const paper of data.papers){const cell=document.createElement('th');cell.append(element('strong',paper.code+' · '+paper.title),
      element('p',[(paper.authors||[]).join('、'),paper.year].filter(Boolean).join(' · '),'hint'));headers.append(cell);}head.append(headers);table.append(head);
    const body=document.createElement('tbody');for(const [key,label] of Object.entries(fields)){const line=document.createElement('tr');line.append(element('th',label));
      for(const paper of data.papers){const node=document.createElement('td'),cell=data.cells[paper.code][key];
        if(editable){const input=document.createElement('textarea');input.rows=4;input.maxLength=2000;input.value=cell.text;input.setAttribute('aria-label',paper.code+' '+label);
          input.placeholder='待填写；材料没有提供的内容请明确标记。';input.oninput=()=>{cell.text=input.value;cell.reviewed=false;review.checked=false;changed();};node.append(input);
          const references=element('div','', 'comparison-references');
          for(const source of data.sources.filter(source=>source.paper===paper.code)){const tag=element('label','', 'inline-label');
            const check=document.createElement('input');check.type='checkbox';check.checked=cell.citations.includes(source.label);
            check.onchange=()=>{cell.citations=check.checked?[...new Set([...cell.citations,source.label])]:cell.citations.filter(value=>value!==source.label);
              cell.reviewed=false;review.checked=false;changed();};tag.append(check,document.createTextNode(source.label+(source.page?' · 第 '+source.page+' 页':' · '+(kinds[source.kind]||source.kind))));references.append(tag);}
          node.append(references);const tag=element('label','', 'inline-label');const review=document.createElement('input');review.type='checkbox';review.checked=cell.reviewed;
          review.onchange=()=>{cell.reviewed=review.checked;changed();};tag.append(review,document.createTextNode('本人已核对'));node.append(tag);
        }else{node.append(element('p',cell.text||'材料未提供'));node.append(element('small',cell.citations.map(value=>'['+value+']').join(' ')));}
        line.append(node);}body.append(line);}table.append(body);container.append(table);}
  function renderSources(container,sources){container.replaceChildren();for(const source of sources){const box=element('article','', 'ai-evidence');
    box.append(element('strong','['+source.label+'] '+source.paper+' · '+source.title));
    box.append(element('p',(kinds[source.kind]||source.kind)+(source.page?' · PDF 第 '+source.page+' 页':' · 无 PDF 页码')+
      (source.truncated?' · 文字已截短':'')+(source.current===false?' · 当前原文已变化或不可用，保留的是旧快照':''),'hint'));
    box.append(element('pre',source.text,'changelog'));if(source.pdf_url){const link=element('a','回到原文对应页 ↗');link.href=source.pdf_url;link.target='_blank';link.rel='noopener';box.append(link);}container.append(box);}}
  el('comparison-title').oninput=changed;
  el('comparison-save').onclick=()=>working(async()=>{if(!board)return;
    const saved=await api('/api/comparisons/save',{identity:board.id,revision:board.revision,title:el('comparison-title').value,cells:board.cells});
    dirty=false;await loadBoards(saved.id);await openBoard(saved.id);notice('对照表及核对状态已保存。');});
  el('comparison-archive').onclick=()=>{if(!board||!keepEdits())return;working(async()=>{
    const saved=await api('/api/comparisons/archive',{identity:board.id,revision:board.revision,archived:!board.archived});
    el('comparison-include-archived').checked=true;await loadBoards(saved.id);await openBoard(saved.id);notice(saved.archived?'已归档，内容继续保留。':'对照表已恢复。');});};
  el('comparison-discard').onclick=()=>{if(board)working(()=>openBoard(board.id));};
  async function loadConnections(){const previous=el('comparison-ai-connection').value;
    const data=await read('/api/ai/profiles');el('comparison-ai-connection').replaceChildren();
    for(const profile of data.profiles){const option=element('option',profile.name+' · '+profile.model);option.value=profile.id;el('comparison-ai-connection').append(option);}
    if(data.profiles.some(profile=>profile.id===previous))el('comparison-ai-connection').value=previous;}
  document.addEventListener('researchprofilechange',invalidate);el('comparison-ai-connection').onchange=invalidate;el('comparison-ai-question').oninput=invalidate;
  el('comparison-ai-prepare').onclick=()=>{if(!board||!keepEdits())return;working(async()=>{
    if(candidate){notice('请先另存或关闭当前 AI 草稿，再生成新的草稿。',true);return;}
    invalidate();preview=await api('/api/ai/comparison/preview',{identity:board.id,profile_id:el('comparison-ai-connection').value,question:el('comparison-ai-question').value});
    el('compare-preview').hidden=false;el('compare-destination').textContent=preview.name+' · '+preview.model+' · '+preview.base_url+' · '+preview.research_profile;
    el('compare-full-prompt').textContent='系统提示：\n'+preview.system+'\n\n输入：\n'+preview.prompt;
    el('compare-output-hint').textContent=`本次 ${preview.sources.length} 个片段，最多输出 ${preview.max_output_tokens} tokens；可能计费。预览十分钟有效，发送一次。`;
    notice('已在本机生成比较预览；尚未调用 AI。');});};
  el('compare-send').onclick=()=>{if(!preview||!el('compare-consent').checked){notice('请先预览并确认发送范围及费用。',true);return;}
    working(async()=>{const confirmation=preview.confirmation;invalidate();notice('正在请求结构化比较草稿，最长等待约两分钟…');
      candidate=await api('/api/ai/comparison/ask',{confirmation,consent:true});
      el('compare-ai-result').hidden=false;el('compare-ai-message').textContent=candidate.message+
        ` 服务商报告：输入 ${candidate.usage.input_tokens??'未知'}，输出 ${candidate.usage.output_tokens??'未知'} tokens。`;
      renderMatrix(el('compare-ai-matrix'),candidate,false);notice('AI 草稿已通过结构和来源编号检查；未覆盖原表，请人工核对。');});};
  el('compare-adopt').onclick=()=>{if(!candidate||!keepEdits())return;working(async()=>{
    const saved=await api('/api/ai/comparison/adopt',{identity:candidate.id});candidate=null;
    await loadBoards(saved.id);await openBoard(saved.id);notice('已另存为 AI 草稿对照表，原表保留。');});};
  el('compare-discard-ai').onclick=()=>{candidate=null;el('compare-ai-result').hidden=true;notice('已关闭当前 AI 草稿预览。');};
  function attachNative(){const bridge=window.pywebview&&window.pywebview.api;if(!bridge)return;
    for(const [id,format] of [['compare-export-md','md'],['compare-export-csv','csv']]){el(id).hidden=false;el(id).onclick=async()=>{
      if(!board||!keepEdits()||busy||exporting)return;exporting=true;
      try{const result=await bridge.export_comparison(board.id,format,board.revision);if(result.saved)notice('对照表和来源快照已导出到选定的本机文件。');}
      catch(error){notice(error.message,true);}finally{exporting=false;}};}}
  window.addEventListener('pywebviewready',attachNative);attachNative();
  async function loadAnnotations(){const result=await read('/api/annotations?query='+encodeURIComponent(el('annotations-query').value)+
    '&include_missing='+el('annotations-missing').checked+'&offset='+annotationOffset);
    annotationTotal=result.total;annotationShown=result.records.length;
    el('annotations-list').replaceChildren();el('annotations-page').textContent=result.records.length?
      `共 ${result.total} 条，本页 ${result.offset+1}–${result.offset+result.records.length}。`:`共 ${result.total} 条，本页无记录。`;
    el('annotations-prev').disabled=annotationOffset===0;el('annotations-next').disabled=annotationOffset+result.records.length>=result.total;
    for(const row of result.records){const box=element('article','', 'result');box.append(element('h3',row.citation.title));
      box.append(element('small',[(row.citation.authors||[]).join('、'),row.citation.year,
        row.page?'PDF 第 '+row.page+' 页（标签 '+(row.page_label||'未提供')+'）':'无有效 PDF 页序',row.current?'本次已返回':'本次未返回，保留快照'].filter(Boolean).join(' · ')));
      const typeName=({highlight:'高亮',underline:'下划线',note:'便签',text:'文本',image:'图像',ink:'手绘'})[row.type]||row.type;
      box.append(element('p','类型：'+typeName+(row.color?' · 颜色 '+row.color:'')+(row.tags.length?' · 标签 '+row.tags.join('、'):'')+
        (row.truncated?' · 超长文字或标签已截短，请回到 Zotero 查看完整内容':''),'hint'));
      box.append(element('strong','摘录'),element('pre',row.text||'无文字摘录；图像或手绘本体未导入。'),element('strong','个人批注'),element('pre',row.comment||'无评论'));
      if(row.pdf_url){const link=element('a','查看原文页 ↗');link.href=row.pdf_url;link.target='_blank';link.rel='noopener';box.append(link);}
      const button=element('button','保存为独立阅读笔记','secondary');button.onclick=()=>working(async()=>{
        await api('/api/annotations/note',{identity:row.id,revision:row.revision});notice('批注快照已另存为阅读笔记，后续同步不会覆盖笔记。');});box.append(button);el('annotations-list').append(box);}
    if(!result.records.length)el('annotations-list').textContent='没有匹配批注。保持 Zotero 打开并点击“同步 Zotero”；旧版 API 可能不返回批注，空列表不代表 Zotero 中一定没有批注。';}
  el('annotations-search').onsubmit=event=>{event.preventDefault();annotationOffset=0;working(loadAnnotations);};
  el('annotations-missing').onchange=()=>{annotationOffset=0;working(loadAnnotations);};
  el('annotations-prev').onclick=()=>{annotationOffset=Math.max(0,annotationOffset-50);working(loadAnnotations);};
  el('annotations-next').onclick=()=>{annotationOffset+=50;working(loadAnnotations);};
  document.querySelector('[data-view="annotations-view"]').addEventListener('click',()=>working(loadAnnotations));
  document.querySelector('[data-view="literature-view"]').addEventListener('click',()=>working(async()=>{
    await loadBoards();
    if(board){if(!dirty&&!candidate)await openBoard(board.id);else await loadConnections();}
  }));
  renderBasket();
})();
