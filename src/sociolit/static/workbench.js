(() => {
  const go = id=>{showView(id);document.querySelector(`[data-view="${id}"]`).click();};
  el('maint-sync').onclick=()=>el('import').click();
  el('maint-model').onclick=()=>go('settings-view');
  el('maint-ai').onclick=()=>window.openOrganizingTask();
  el('maint-connections').onclick=()=>{go('ai-view');el('ai-settings').open=true;el('ai-settings').scrollIntoView({behavior:'auto',block:'start'});};
  async function maintenance(){
    try{
      const response=await fetch('/api/maintenance',{headers:{'X-Sociolit-Token':token}});if(!response.ok)throw Error('读取整理状态失败');
      const data=await response.json();el('maintenance-message').textContent=data.message;
      const s=data.last_import, a=s.annotations||{};
      el('maintenance-summary').textContent=Object.keys(s).length?`最近同步：变更 ${s.items_changed||0} 条书目，复用 ${s.files_unchanged||0} 个附件，重建 ${s.files_indexed||0} 个附件，批注返回 ${a.returned??'未提供'} 条。`:'尚无同步记录。';
      el('workflow-summary').textContent=data.workflow.message||'已准备模型且建立过文件夹语义试点后，同步可以自动补齐新增片段；首次构建由你启动。';
      el('duplicate-summary').textContent=`发现 ${data.duplicates.total} 组重复候选，最多显示40组。${data.duplicates.message}`;
      el('duplicate-list').replaceChildren();
      for(const group of data.duplicates.groups){const article=document.createElement('article');article.className='result';const title=document.createElement('strong');title.textContent=group.reason;article.append(title);for(const item of group.items){const row=document.createElement('p');row.textContent=item.title;article.append(row);}el('duplicate-list').append(article);}
    }catch(error){notice(error.message,true);}
  }
  el('maintenance-refresh').onclick=maintenance;
  document.querySelector('[data-view="maintenance-view"]').addEventListener('click',maintenance);

})();
