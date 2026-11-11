(() => {
  let loaded = false, dirty = false;
  const themes = {silver:'银白',sage:'竹青',ocean:'海盐蓝',paper:'暖纸',ink:'墨夜',lavender:'紫藤',teal:'松石',rose:'玫瑰',contrast:'高对比',system:'跟随系统'};
  const system = matchMedia('(prefers-color-scheme: dark)');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let current = {theme:'silver',motion:'gentle',density:'comfortable',auto_embed:true};
  function apply(values) {
    current = {...values};
    document.documentElement.dataset.theme = values.theme === 'system' ? (system.matches?'ink':'silver') : values.theme;
    document.documentElement.dataset.motion = reduced.matches?'none':values.motion;
    document.documentElement.dataset.density = values.density;
    document.querySelectorAll('[data-theme-choice]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.themeChoice===values.theme)));
  }
  system.addEventListener('change',()=>apply(current)); reduced.addEventListener('change',()=>apply(current));
  window.animateView = view => {
    document.querySelectorAll('.view').forEach(v=>v.getAnimations().forEach(a=>a.cancel()));
    if (!reduced.matches && current.motion!=='none') view.animate(
      [{opacity:0,transform:'translateY(3px)'},{opacity:1,transform:'translateY(0)'}],
      {duration:current.motion==='quick'?80:140,easing:'cubic-bezier(.2,.7,.2,1)'});
  };
  window.loadAppearance = async()=>{
    if(loaded || !token)return;
    loaded=true;
    try {
      const response=await fetch('/api/appearance',{headers:{'X-Sociolit-Token':token}});
      if(!response.ok)throw Error('读取外观设置失败');
      const value=await response.json(); apply(value);
      for(const key of ['theme','motion','density'])el('appearance-'+key).value=value[key];
      el('auto-embed').checked=value.auto_embed;
    } catch(error){loaded=false;notice(error.message,true);}
  };
  const values = ()=>({theme:el('appearance-theme').value,motion:el('appearance-motion').value,density:el('appearance-density').value,auto_embed:el('auto-embed').checked});
  for(const [key,name] of Object.entries(themes)) {
    const option=document.createElement('option');option.value=key;option.textContent=name;el('appearance-theme').append(option);
    const button=document.createElement('button');button.type='button';button.className='theme-choice';button.dataset.themeChoice=key;
    button.textContent=name;button.setAttribute('aria-pressed','false');
    button.onclick=()=>{el('appearance-theme').value=key;apply(values());dirty=true;el('appearance-state').textContent='正在预览，点击保存后下次继续沿用。';};el('theme-choices').append(button);
  }
  el('appearance-form').addEventListener('input',()=>{dirty=true;apply(values());el('appearance-state').textContent='正在预览，尚未保存。';});
  el('appearance-form').onsubmit=async event=>{event.preventDefault();try{const result=await api('/api/appearance',values());apply(result);dirty=false;el('appearance-state').textContent='已保存到本机，下次打开继续沿用。';}catch(error){notice(error.message,true);}};
  window.isAppearanceDirty=()=>dirty;
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
  if(token)window.loadAppearance();
})();
