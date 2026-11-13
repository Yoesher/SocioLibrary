/* Local subscription editing; network checks are handled by the bounded metadata service. */
(() => {
  let journals=[],signature='',busy=false,dirty=false,working=false;
  const labels={rss:'官网 RSS / Atom',crossref:'Crossref · ISSN',openalex:'OpenAlex · ISSN',builtin:'内置官网目录'};
  const make=(tag,text='',cls='')=>{const n=document.createElement(tag);n.textContent=text;n.className=cls;return n;};
  window.isJournalBusy=()=>working;window.isJournalDirty=()=>dirty;
  function message(text,error=false){el('journal-message').textContent=text;el('journal-message').className=error?'hint error':'hint';}
  function providerFields(){const source=el('journal-provider').value;el('journal-rss-fields').hidden=source!=='rss';el('journal-issn-fields').hidden=!['crossref','openalex'].includes(source);el('journal-url').required=source==='rss';el('journal-issns').required=['crossref','openalex'].includes(source);el('journal-provider-hint').textContent={rss:'只接受公开 HTTPS RSS / Atom；保存前检查真实格式和频道刊名。',crossref:'从期刊官网复制 ISSN。验证结果会显示数据库返回的刊名，请核对。',openalex:'需在本机配置 OPENALEX_API_KEY 并重启软件。不要将密钥填入表单。',builtin:'恢复软件内置的官网目录来源，不改变已入库文献。'}[source];}
  function edit(journal=null){
    if(working||busy){message('请等待当前任务完成。',true);return;}
    if(dirty){message('请先保存或取消当前订阅修改。',true);return;}
    el('journal-editor').hidden=false;el('journal-editor-title').textContent=journal?'修改订阅来源':'添加期刊';
    el('journal-name').value=journal?.name||'';el('journal-name').readOnly=!!journal;
    const builtin=el('journal-provider').querySelector('[value=builtin]');builtin.hidden=!journal?.builtin_available;builtin.disabled=!journal?.builtin_available;
    el('journal-provider').value=journal?.provider==='builtin'&&!journal.builtin_available?'rss':journal?.provider||'rss';
    el('journal-url').value=journal?.rss_url||'';el('journal-issns').value=(journal?.issns||[]).join(', ');el('journal-feed-title').value=journal?.feed_title||'';
    providerFields();el('journal-editor').scrollIntoView({block:'nearest',behavior:'instant'});el(journal?'journal-provider':'journal-name').focus();
  }
  function render(){
    const box=el('journals');box.replaceChildren();
    for(const j of journals){
      const card=make('article','','journal-card'),heading=make('h3',j.name),state=make('p',j.enabled?'正在订阅':j.provider==='builtin'&&!j.builtin_available?'待接入':'已暂停',j.enabled?'journal-enabled':'');
      card.append(heading,state,make('p',j.provider==='builtin'&&!j.builtin_available?'尚未配置来源':labels[j.provider]||'目录来源'));
      if(j.source_title)card.append(make('p','来源刊名：'+j.source_title));
      if(j.issns?.length)card.append(make('p','ISSN '+j.issns.join(' / ')));
      if(j.status==='official_current_snapshot')card.append(make('p','仅检查官网当期快照'));
      const actions=make('div','','toolbar'),change=make('button','修改来源','secondary');change.type='button';change.disabled=busy||working;change.setAttribute('aria-label','修改 '+j.name+' 的来源');change.onclick=()=>edit(j);actions.append(change);
      if(j.enabled||j.provider!=='builtin'||j.builtin_available){const toggle=make('button',j.enabled?'暂停':'恢复订阅','secondary');toggle.type='button';toggle.disabled=busy||working;toggle.setAttribute('aria-label',(j.enabled?'暂停 ':'恢复 ')+j.name+' 的订阅');toggle.onclick=async()=>{working=true;render();try{await api('/api/journals/toggle',{name:j.name,enabled:!j.enabled});message(j.enabled?'已暂停后续检查；已有文献保留。':'订阅已恢复，可点击“立即检查”。');signature='';await refresh();}catch(error){message(error.message,true);}finally{working=false;render();}};actions.append(toggle);}
      if(j.homepage){const link=make('a','期刊官网 ↗');link.href=j.homepage;link.target='_blank';link.rel='noopener';actions.append(link);}
      card.append(actions);box.append(card);
    }
    el('journal-new').disabled=busy||working;el('journal-save').disabled=busy||working;
    el('journal-form').querySelectorAll('input,select').forEach(field=>{field.disabled=busy||working;});el('journal-cancel').disabled=working;
  }
  window.renderJournalSubscriptions=(values,isBusy)=>{const next=JSON.stringify(values)+'|'+isBusy;if(next===signature)return;signature=next;journals=values;busy=isBusy;render();};
  el('journal-new').onclick=()=>edit();
  window.prepareResearchJournal=starter=>{
    if(working||busy||dirty){message('请先完成当前期刊编辑或资料任务。',true);notice('请先完成当前期刊编辑或资料任务。',true);return;}
    showView('journal-view');
    const existing=journals.find(row=>row.name===starter.name);
    edit(existing||null);
    if(!existing){el('journal-name').value=starter.name;el('journal-provider').value='crossref';el('journal-issns').value=starter.issn;providerFields();dirty=true;}
    message('这是研究领域的期刊起点，尚未新增订阅。核对刊名和 ISSN 后点击“验证并保存”。');
  };
  el('journal-cancel').onclick=()=>{if(working)return;dirty=false;el('journal-editor').hidden=true;message('已取消本次编辑，原订阅保留。');};
  el('journal-form').addEventListener('input',()=>{dirty=true;});
  el('journal-provider').onchange=()=>{dirty=true;providerFields();};
  el('journal-form').onsubmit=async event=>{
    event.preventDefault();if(working||busy)return;working=true;render();message('正在验证订阅来源；成功后才保存…');
    try{const result=await api('/api/journals',{name:el('journal-name').value.trim(),provider:el('journal-provider').value,url:el('journal-url').value.trim(),issns:el('journal-issns').value.split(/[,，;；\s]+/).filter(Boolean),feed_title:el('journal-feed-title').value.trim()});
      dirty=false;el('journal-editor').hidden=true;message('已保存并启用。来源刊名：'+result.source_title+(result.records_in_window===null?'':'；近90天频道内 '+result.records_in_window+' 条。')+' 请核对刊名后点击“立即检查”。');signature='';await refresh();
    }catch(error){message(error.message,true);}finally{working=false;render();}
  };
  providerFields();
})();
