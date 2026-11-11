(() => {
  const positions=new Map(), history=[];let current='search-view';
  const titles={
    'search-view':'摘要、研究线索与原文，放在一起。','graph-view':'从一篇文献出发，看清研究之间的联系。',
    'literature-view':'发现相似研究，并排比较文献。','annotations-view':'把阅读时留下的线索重新连接起来。'
  };
  window.navigateWorkspace=(id,back=false)=>{
    if(!el(id)||!el(id).classList.contains('view'))return;
    if(id!==current){positions.set(current,window.scrollY);if(!back)history.push(current);current=id;}
    document.body.dataset.view=id;document.querySelectorAll('.view').forEach(v=>v.hidden=v.id!==id);
    document.querySelectorAll('.nav').forEach(n=>{n.classList.toggle('active',n.dataset.view===id);if(n.dataset.view===id)n.setAttribute('aria-current','page');else n.removeAttribute('aria-current');});
    const nav=document.querySelector(`.nav[data-view="${id}"]`);
    document.querySelector('main > header h1').textContent=id==='paper-view'?'文献详情':nav?.textContent||'研究工作台';
    document.querySelector('main > header .subtle').textContent=titles[id]||'你的资料、设置与研究进度保存在本机。';
    el('workspace-back').disabled=!history.length;window.scrollTo({top:positions.get(id)||0,behavior:'instant'});
    window.animateView?.(el(id));document.dispatchEvent(new CustomEvent('workspaceview',{detail:id}));
  };
  el('workspace-back').onclick=()=>{const previous=history.pop();if(previous)window.navigateWorkspace(previous,true);};
  const icons={
    'search-view':'M21 21l-5-5 M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
    'reading-view':'M3 4h7l2 2 2-2h7v16h-7l-2 2-2-2H3z M12 6v16',
    'annotations-view':'M5 3h14v18H5z M8 8h8 M8 12h8 M8 16h5',
    'journal-view':'M3 5h18v15H3z M3 9h18 M8 2v5 M16 2v5',
    'literature-view':'M3 4h7v16H3z M14 4h7v16h-7z',
    'graph-view':'M10 6l8 4 M7 8l-2 8 M8 18l9-5 M9 5a3 3 0 1 1-6 0 3 3 0 0 1 6 0 M23 11a3 3 0 1 1-6 0 3 3 0 0 1 6 0 M8 19a3 3 0 1 1-6 0 3 3 0 0 1 6 0',
    'ai-view':'M12 2l3 7 7 3-7 3-3 7-3-7-7-3 7-3z',
    'research-view':'M5 3h14v18H5z M8 7h8 M8 11h8 M8 15h4',
    'maintenance-view':'M3 7h7l2-3h9v16H3z M8 12h8 M12 8v8',
    'software-view':'M5 8a8 8 0 1 1-1 7 M2 3v6h6 M12 7v6l4 2',
    'settings-view':'M4 6h16 M4 12h16 M4 18h16 M8 3v6 M16 9v6 M10 15v6'
  };
  const groups=[['资料库',['search-view','reading-view','annotations-view','journal-view']],['研究',['literature-view','graph-view','ai-view','research-view']],['应用',['maintenance-view','software-view','settings-view']]];
  const nav=document.querySelector('.sidebar nav');
  for(const [label,views] of groups){const group=document.createElement('div');group.className='nav-group';const title=document.createElement('p');title.className='nav-group-label';title.textContent=label;group.append(title);
    for(const id of views){const row=document.querySelector(`.nav[data-view="${id}"]`);const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');icon.setAttribute('viewBox','0 0 24 24');icon.setAttribute('aria-hidden','true');const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d',icons[id]);icon.append(path);row.prepend(icon);group.append(row);}nav.append(group);
  }
})();
