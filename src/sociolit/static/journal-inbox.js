(() => {
  let offset=0,serial=0,controller=null;
  const make=(tag,text='',cls='')=>{const n=document.createElement(tag);n.textContent=text;n.className=cls;return n;};
  async function load(reset=false,scroll=false){
    if(reset)offset=0;const current=++serial;controller?.abort();controller=new AbortController();const own=controller;
    const params=new URLSearchParams({query:el('journal-inbox-query').value.trim(),journal:el('journal-inbox-journal').value,state:el('journal-inbox-state').value,offset,limit:20});
    try{const response=await fetch('/api/journals/inbox?'+params,{headers:{'X-Sociolit-Token':token},signal:own.signal});if(!response.ok)throw Error('收件箱暂时不可用，请等待资料任务完成后刷新。');const result=await response.json();if(current!==serial)return;
      if(offset>=result.total&&offset>0){offset=Math.max(0,Math.ceil(result.total/20)-1)*20;return load();}
      const select=el('journal-inbox-journal'),selected=select.value;select.replaceChildren(new Option('全部期刊',''));for(const journal of result.journals)select.append(new Option(journal,journal));select.value=selected;
      el('journal-inbox-summary').textContent='符合条件 '+result.total+' 篇 · 全部未读 '+result.unread+' 篇';el('journal-inbox-page').textContent=(result.total?Math.floor(offset/20)+1:0)+' / '+Math.ceil(result.total/20);el('journal-inbox-prev').disabled=offset===0;el('journal-inbox-next').disabled=offset+20>=result.total;
      const box=el('journal-inbox-list');box.replaceChildren();if(scroll)el('journal-inbox-summary').scrollIntoView({block:'start',behavior:'instant'});if(!result.records.length)box.append(make('p','当前没有符合条件的文献。检查期刊更新后，新书目会出现在这里。','hint'));
      for(const row of result.records){const card=make('article','','inbox-card');card.append(make('h4',row.title),make('p',[row.journal,...row.authors,row.year].filter(Boolean).join(' · ')),make('p','发表日期：'+(row.published_date||'来源未注明')+' · 首次发现：'+row.first_seen.slice(0,10)+(row.updated_record?' · 书目已更新':'')+' · '+(row.read?'已读':'未读')));
        const actions=make('div','','toolbar'),read=make('button',row.read?'标为未读':'标为已读','secondary'),star=make('button',row.favorite?'★ 已收藏':'☆ 收藏','secondary');
        const update=async change=>{try{await api('/api/journals/inbox/mark',{item_id:row.item_id,...change});await load();}catch(e){el('journal-inbox-summary').textContent=e.message;}};
        read.onclick=()=>update({read:!row.read});star.onclick=()=>update({favorite:!row.favorite});const paper=make('button','文献详情','secondary');paper.onclick=()=>window.openPaper(row.item_id,row.title);const graph=make('button','查看关联','secondary');graph.onclick=()=>window.openLiteratureGraph(row.item_id);actions.append(paper,graph,read,star);
        if(row.url){const link=make('a','来源页面 ↗');link.href=row.url;link.target='_blank';link.rel='noopener';actions.append(link);}card.append(actions);box.append(card);
      }
    }catch(e){if(e.name!=='AbortError'&&current===serial)el('journal-inbox-summary').textContent=e.message;}
  }
  document.addEventListener('journalupdated',()=>{if(!el('journal-view').hidden)load();});
  el('journal-inbox-form').onsubmit=e=>{e.preventDefault();load(true,true);};
  el('journal-inbox-prev').onclick=()=>{offset=Math.max(0,offset-20);load(false,true);};el('journal-inbox-next').onclick=()=>{offset+=20;load(false,true);};
  document.addEventListener('workspaceview',e=>{if(e.detail==='journal-view')load();else{serial++;controller?.abort();}});
})();
