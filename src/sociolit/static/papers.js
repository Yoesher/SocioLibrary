/* Paper-first results. Source snapshots stay intact when moving between pages. */
(() => {
  let session='', offset=0, shownOffset=0, total=0, pageSize=10, request=null, itemFilter='';
  const make=(tag,text='',className='')=>{const n=document.createElement(tag);n.textContent=text;n.className=className;return n;};
  const button=(text,action,cls='secondary')=>{const n=make('button',text,cls);n.type='button';n.onclick=action;return n;};
  function busy(value){searchBusy=value;el('search-button').disabled=value;for(const id of ['papers-prev','papers-top-prev'])el(id).disabled=value||offset===0;for(const id of ['papers-next','papers-top-next'])el(id).disabled=value||offset+pageSize>=total;el('papers-size').disabled=value;el('results').setAttribute('aria-busy',String(value));}
  function highlight(text,terms){
    const node=make('p','','evidence-text');const sorted=[...new Set(terms||[])].sort((a,b)=>b.length-a.length);
    if(!sorted.length){node.textContent=text;return node;}
    const pattern=new RegExp(sorted.map(t=>t.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')).join('|'),'gi');let start=0;
    for(const match of text.matchAll(pattern)){node.append(document.createTextNode(text.slice(start,match.index)),make('mark',match[0]));start=match.index+match[0].length;}
    node.append(document.createTextNode(text.slice(start)));return node;
  }
  window.sourceLink=(source,label)=>{
    const link=make('a',label||(source.zotero_url?`在 Zotero 中打开第 ${source.page} 页`:'查看本机 PDF 对应页'),'source-link');
    link.href=source.zotero_url||source.pdf_url;link.dataset.fileId=source.file_id;link.dataset.page=source.page;return link;
  };
  // Shared by search, recommendations, comparisons, AI citations and annotations.
  document.addEventListener('click',async event=>{
    const a=event.target.closest('a');if(!a)return;
    let file=a.dataset.fileId, page=Number(a.dataset.page);
    if(!file&&a.getAttribute('href')?.startsWith('/api/pdf/')){
      const url=new URL(a.href);file=decodeURIComponent(url.pathname.slice('/api/pdf/'.length));page=Number(new URLSearchParams(url.hash.slice(1)).get('page'));
    }
    if(!file||!page||a.dataset.preview==='true')return;
    event.preventDefault();if(a.getAttribute('aria-busy')==='true')return;a.setAttribute('aria-busy','true');
    try{
      const target=await api('/api/source/location',{file_id:file,page});
      if(target.zotero_url){
        const bridge=window.pywebview?.api;
        if(bridge){const result=await bridge.open_source(file,page);if(!result.opened)throw Error(result.message);}
        else window.location.href=target.zotero_url;
        notice(`已请求 Zotero 打开 PDF 第 ${page} 页。`);
      }else window.open(target.pdf_url,'_blank','noopener');
    }catch(error){notice(error.message,true);}finally{a.removeAttribute('aria-busy');}
  });
  function note(source){
    if(window.hasUnsavedNote?.()){notice('请先保存当前阅读笔记，再建立新笔记。',true);return;}
    noteChunk=source.id;noteDigest=source.source_digest;el('note-id').value='';el('note-title').value=source.title;el('note-body').value='';
    el('note-source').textContent=(source.page?`PDF 第 ${source.page} 页`:'书目信息')+' · 将保存当前摘录快照';showView('research-view');loadResearch();el('note-body').focus();
  }
  function card(paper,index,detail=false){
    const box=make('article','','result paper-card');box.dataset.itemId=paper.item_id;
    const top=make('div','','paper-heading'), number=make('span',detail?'文献':String(offset+index+1).padStart(2,'0'),'paper-number');
    const heading=make('div');heading.append(make('h3',paper.title),make('p',[(paper.authors||[]).join('、'),paper.year,paper.journal].filter(Boolean).join(' · '),'paper-meta'));top.append(number,heading);box.append(top);
    const abstract=make('section','','paper-section');abstract.append(make('h4','论文摘要'),make('p',paper.abstract.text||'暂无摘要。可在 Zotero 中补充摘要后同步。','abstract-text'),make('small',paper.abstract.source,'provenance'));box.append(abstract);
    const relation=make('section','','paper-section relation-section');relation.append(make('h4','与本次查询的关系'),make('p',paper.relation));if(paper.relation_excerpt)relation.append(make('blockquote','摘要中的对应表述：“'+paper.relation_excerpt+'”'));relation.append(make('small','依据本机检索命中生成 · 未调用云端 AI','provenance'));box.append(relation);
    const evidence=make('section','','paper-section');evidence.append(make('h4','原文命中页'));
    const pages=make('div','','page-chips'), pane=make('div','','evidence-pane');evidence.append(pages,pane);box.append(evidence);
    const quick=make('div','','paper-quick');box.append(quick);const tools=make('details','','paper-tools'), summary=make('summary','阅读与研究操作');tools.append(summary);box.append(tools);
    function showSource(source){
      pane.replaceChildren();tools.replaceChildren(summary);quick.replaceChildren();pages.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(Number(b.dataset.id)===source.id)));
      if(source.page){
        pane.append(make('small',`PDF 第 ${source.page} 页 · 文件页标签 ${source.page_label||source.page}${source.kind==='ocr'?' · OCR，需核对':''}`,'page-location'),highlight(source.text,source.matched_terms));
        const actions=make('div','','evidence-actions');actions.append(window.sourceLink(source));
        const preview=make('a','本机 PDF 预览','pdf-fallback');preview.href=source.pdf_url;preview.dataset.preview='true';preview.target='_blank';preview.rel='noopener';actions.append(preview);pane.append(actions);
      }
      source={...source,reading:paper.reading,authors:paper.authors,year:paper.year,journal:paper.journal};
      const row=make('div','','toolbar');row.append(button('写阅读笔记',()=>note(source)),button('复制出处与摘录',async()=>{try{await navigator.clipboard.writeText([paper.title,(paper.authors||[]).join('、'),source.page?`PDF 第 ${source.page} 页`:'书目信息',source.text].join('\n'));notice('已复制出处与摘录。');}catch{notice('请手动选择文字复制。',true);}}));tools.append(row);
      window.enhanceReadingResult?.(tools,source);window.enhanceAIResult?.(tools,source);window.enhanceLiteratureResult?.(quick,source);window.enhanceGraphResult?.(quick,source);
    }
    if(paper.evidence.length){for(const source of paper.evidence){const b=button(`第 ${source.page} 页`,()=>showSource(source),'page-chip');b.dataset.id=source.id;b.setAttribute('aria-pressed','false');pages.append(b);}showSource(paper.evidence[0]);}
    else{if(paper.representative)showSource(paper.representative);pane.append(make('p',paper.evidence_message,'hint'));}
    return box;
  }
  async function run(fresh=false){
    if(searchBusy)return;
    if(fresh){session='';offset=0;request={query:el('query').value.trim(),mode:el('mode').value,author:el('author').value.trim(),year:el('year').value.trim(),item_id:itemFilter};itemFilter='';}
    if(!request?.query)return;
    busy(true);notice('正在查找相关文献…');
    try{
      const result=await api('/api/search/papers',{...request,session,offset,page_size:pageSize});shownOffset=offset;document.body.dataset.search='results';
      session=result.session;total=result.total;lastQuery={query:request.query,mode:request.mode,author:request.author,year:request.year};
      window.resetReadingControls?.();window.resetAIControls?.();el('results').replaceChildren(...result.papers.map((paper,index)=>card(paper,index)));
      const info=result.search_info;el('search-explanation').hidden=!info;
      if(info)el('search-explanation').textContent=info.message+(info.expanded_queries?.length?' 中英术语：'+info.expanded_queries.join(' / '):'')+(info.semantic_scope?' 语义范围：'+info.semantic_scope+'（语义候选最多100篇）。':'');
      el('result-summary').textContent=total?`共 ${total} 篇候选文献 · 当前 ${offset+1}–${offset+result.papers.length} 篇`:'未找到匹配文献';
      el('papers-page').textContent=`第 ${Math.floor(offset/pageSize)+1} / ${Math.max(1,Math.ceil(total/pageSize))} 页`;el('papers-top-page').textContent=el('papers-page').textContent;el('papers-pagination').hidden=!total;el('papers-top').hidden=!total;
      if(!total)el('results').append(make('div','暂未找到文献。可以减少关键词，或移除作者、年份筛选。','empty'));
      if(!fresh)el('result-summary').scrollIntoView({block:'start',behavior:'instant'});
      notice('检索完成。');
    }catch(error){offset=shownOffset;notice(error.message,true);}finally{busy(false);}
  }
  el('search').onsubmit=event=>{event.preventDefault();run(true);};
  el('papers-prev').onclick=()=>{if(offset>0&&!searchBusy){offset=Math.max(0,offset-pageSize);run();}};
  el('papers-next').onclick=()=>{if(offset+pageSize<total&&!searchBusy){offset+=pageSize;run();}};
  el('papers-top-prev').onclick=()=>el('papers-prev').click();el('papers-top-next').onclick=()=>el('papers-next').click();
  el('papers-size').onchange=()=>{pageSize=Number(el('papers-size').value);offset=0;run();};
  window.openPaper=async(identity,title)=>{
    if(searchBusy)return;busy(true);showView('paper-view');el('paper-detail').replaceChildren(make('p','正在读取摘要与原文…','hint'));
    try{const paper=await api('/api/literature/paper',{item_id:identity,query:lastQuery?.query||''});el('paper-detail').replaceChildren(card(paper,0,true));notice('已打开文献详情；返回可继续原来的检索或图谱。');}
    catch(error){el('paper-detail').replaceChildren(make('p',error.message,'error'));notice(error.message,true);}finally{busy(false);}
  };
  document.addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'){event.preventDefault();showView('search-view');el('query').focus();el('query').select();}});
})();
