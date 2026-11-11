/* Design selection changes the complete shell; color is a separate preference. */
(() => {
  let loaded=false, dirty=false, saved=null;
  const designs={
    apple:{name:'Apple · 轻透工作台',description:'悬浮侧栏、轻透工具栏、安静的阅读纸面'},
    fluent:{name:'Windows · 高效工作区',description:'停靠导航、分层工作区、利落的控件与选中标记'},
    material:{name:'Material · 灵感空间',description:'导航轨、大圆角容器、舒展标题与柔和层次'}
  };
  const themes={silver:'标准浅色',sage:'竹青',ocean:'海盐蓝',paper:'暖纸',ink:'墨夜',lavender:'紫藤',teal:'松石',rose:'玫瑰',contrast:'高对比',system:'跟随系统'};
  const system=matchMedia('(prefers-color-scheme: dark)'), reduced=matchMedia('(prefers-reduced-motion: reduce)');
  let current={design:'apple',theme:'silver',motion:'gentle',density:'comfortable',auto_embed:true};
  const make=(tag,text='',cls='')=>{const n=document.createElement(tag);n.textContent=text;n.className=cls;return n;};
  function apply(values,animate=false){
    const changed=['design','theme','density'].some(key=>current[key]!==values[key]);
    current={...current,...values,design:values.design||'apple'};
    const root=document.documentElement;root.dataset.design=current.design;
    root.dataset.theme=current.theme==='system'?(system.matches?'ink':'silver'):current.theme;
    root.dataset.motion=reduced.matches?'none':current.motion;root.dataset.density=current.density;
    if(reduced.matches||current.motion==='none')document.querySelectorAll('main,.view').forEach(v=>v.getAnimations().forEach(a=>a.cancel()));
    document.querySelectorAll('[data-design-choice]').forEach(b=>{const selected=b.dataset.designChoice===current.design;b.setAttribute('aria-checked',String(selected));b.tabIndex=selected?0:-1;});
    document.querySelectorAll('[data-theme-choice]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.themeChoice===current.theme)));
    el('design-current').textContent=designs[current.design].name;
    if(animate&&changed&&!reduced.matches&&current.motion!=='none'){
      const main=document.querySelector('main');main.getAnimations().forEach(a=>a.cancel());
      main.animate([{opacity:.76},{opacity:1}],{duration:current.motion==='quick'?100:220,easing:'cubic-bezier(.2,.7,.2,1)'});
    }
    document.dispatchEvent(new CustomEvent('appearancechange',{detail:{design:current.design}}));
  }
  function sync(values){for(const key of ['design','theme','motion','density'])el('appearance-'+key).value=values[key];el('auto-embed').checked=values.auto_embed;apply(values);}
  function values(){return {design:el('appearance-design').value,theme:el('appearance-theme').value,motion:el('appearance-motion').value,density:el('appearance-density').value,auto_embed:el('auto-embed').checked};}
  function preview(){dirty=true;apply(values(),true);el('appearance-cancel').disabled=!saved;el('appearance-state').textContent='正在预览整套风格；保存后，下次打开继续沿用。';}
  system.addEventListener('change',()=>apply(current));reduced.addEventListener('change',()=>apply(current));
  window.animateView=view=>{
    document.querySelectorAll('.view').forEach(v=>v.getAnimations().forEach(a=>a.cancel()));
    if(reduced.matches||current.motion==='none')return;
    const quick=current.motion==='quick';
    const motion=current.design==='material'?
      {frames:[{opacity:0,transform:'translateY(12px) scale(.985)'},{opacity:1,transform:'translateY(-1px) scale(1)',offset:.85},{opacity:1,transform:'none'}],duration:quick?130:300,easing:'cubic-bezier(.2,.8,.2,1)'}:
      current.design==='fluent'?{frames:[{opacity:0,transform:'translateX(9px)'},{opacity:1,transform:'none'}],duration:quick?90:180,easing:'cubic-bezier(.1,.7,.1,1)'}:
      {frames:[{opacity:0,transform:'translateY(5px) scale(.997)'},{opacity:1,transform:'none'}],duration:quick?100:220,easing:'cubic-bezier(.2,.7,.2,1)'};
    view.animate(motion.frames,{duration:motion.duration,easing:motion.easing});
  };
  for(const [key,design] of Object.entries(designs)){
    const option=make('option',design.name);option.value=key;el('appearance-design').append(option);
    const b=make('button','','design-choice');b.type='button';b.dataset.designChoice=key;b.setAttribute('role','radio');b.setAttribute('aria-checked','false');
    const specimen=make('span','','design-specimen specimen-'+key);specimen.setAttribute('aria-hidden','true');const nav=make('span','','mini-nav');for(let i=0;i<4;i++)nav.append(make('i'));const sheet=make('span','','mini-sheet');sheet.append(make('b'),make('i'),make('i'),make('em'));specimen.append(nav,sheet);
    const copy=make('span','','design-choice-copy');copy.append(make('strong',design.name),make('small',design.description));b.append(specimen,copy);
    b.onclick=()=>{el('appearance-design').value=key;preview();};el('design-choices').append(b);
  }
  el('design-choices').onkeydown=event=>{
    const order=Object.keys(designs),button=event.target.closest('[data-design-choice]');if(!button)return;
    const direction={ArrowRight:1,ArrowDown:1,ArrowLeft:-1,ArrowUp:-1}[event.key];if(!direction&&!['Home','End'].includes(event.key))return;
    event.preventDefault();const index=event.key==='Home'?0:event.key==='End'?order.length-1:(order.indexOf(button.dataset.designChoice)+direction+order.length)%order.length;
    const next=document.querySelector(`[data-design-choice="${order[index]}"]`);next.click();next.focus();
  };
  for(const [key,name] of Object.entries(themes)){
    const option=make('option',name);option.value=key;el('appearance-theme').append(option);
    const b=make('button',name,'theme-choice');b.type='button';b.dataset.themeChoice=key;b.setAttribute('aria-pressed','false');b.onclick=()=>{el('appearance-theme').value=key;preview();};el('theme-choices').append(b);
  }
  for(const event of ['input','change'])el('appearance-form').addEventListener(event,preview);
  el('appearance-cancel').onclick=()=>{if(!saved)return;sync(saved);dirty=false;el('appearance-cancel').disabled=true;el('appearance-state').textContent='已恢复保存的风格，预览没有改动本机设置。';};
  el('appearance-form').onsubmit=async event=>{
    event.preventDefault();const button=el('appearance-save');if(button.disabled)return;button.disabled=true;
    try{const result=await api('/api/appearance',values());saved={...result};sync(result);dirty=false;el('appearance-cancel').disabled=true;el('appearance-state').textContent='已保存整套界面风格，下次打开继续沿用。';}
    catch(error){notice(error.message,true);}finally{button.disabled=false;}
  };
  window.isAppearanceDirty=()=>dirty;
  window.loadAppearance=async()=>{
    if(loaded||!token)return;loaded=true;
    try{const response=await fetch('/api/appearance',{headers:{'X-Sociolit-Token':token}});if(!response.ok)throw Error('读取外观设置失败');saved={design:'apple',...await response.json()};if(!dirty)sync(saved);el('appearance-cancel').disabled=!dirty;}
    catch(error){loaded=false;notice(error.message,true);}
  };
  sync(current);if(token)window.loadAppearance();
})();
