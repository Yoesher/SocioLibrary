let token = '';
let semanticScope = '';
const el = id => document.getElementById(id);
function notice(text, error = false) { el('notice').textContent = text; el('notice').className = error ? 'error' : ''; }
async function api(path, body) {
  const response = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json','X-Sociolit-Token':token}, body:JSON.stringify(body || {})});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '操作失败，请检查配置');
  return data;
}
function fileNotice(file) {
  if (file.status === 'needs_ocr') return file.title + '：没有检测到文字层，需要 OCR。';
  if (file.status === 'missing') return file.title + '：附件未下载、已移动或不在许可目录。';
  if (file.status === 'error') return file.title + '：PDF 未能提取，请检查文件。';
  return file.title + '：部分页面没有检测到文字层，查阅时请核对原文。';
}
async function refresh() {
  const status = await (await fetch('/api/status')).json(); token = status.token;
  el('import').disabled = status.library_busy;
  el('embed').disabled = status.library_busy;
  el('discover').disabled = status.library_busy;
  semanticScope = status.semantic_scope || '';
  const progress = status.semantic_progress;
  el('scope-hint').textContent = semanticScope ? `全文检索覆盖已导入文献；语义检索试点范围为“${semanticScope}”相关文件夹及子文件夹。${progress?`试点索引进度：${progress.done} / ${progress.total} 个片段。`:''}` : '全文检索支持中英文。语义检索需先安装本地模型并构建索引；结果相似度不代表引文证据强度。';
  el('stats').replaceChildren();
  for (const [key,label] of Object.entries({items:'文献与笔记',files:'已处理附件',chunks:'可追溯片段',vectors:'语义向量'})) {
    const box=document.createElement('div'); box.className='stat';
    const number=document.createElement('b'); number.textContent=status.stats[key];
    const name=document.createElement('span'); name.textContent=label; box.append(number,name); el('stats').append(box);
  }
  el('journals').replaceChildren();
  for (const journal of status.journals) {
    const span=document.createElement('span');
    if(journal.homepage){const link=document.createElement('a'); link.href=journal.homepage; link.target='_blank'; link.rel='noopener'; link.textContent=journal.name; span.append(link);} else {span.append(document.createTextNode(journal.name));}
    span.append(document.createTextNode(' · '+(journal.status==='official_current_snapshot'?'当期目录':'enabled' in journal && journal.enabled?'已启用':'来源待接入'))); el('journals').append(span);
  }
  el('warnings').replaceChildren();
  const warnings=[
    ...(status.library_busy?['文献或语义索引正在构建；全文检索可用，导入和手动期刊更新请等待当前任务完成。']:[]),
    ...(status.import_incomplete?['本次或上次导入尚未完成。请等待当前导入；如果已经中断，可再次点击导入继续。']:[]),
    ...(!status.pdf_roots_configured?['尚未设置 PDF 许可目录：导入仅包含书目信息。参照 README 配置一次后即可一键同步。']:[]),
    ...(!status.semantic_model_ready?['本地语义模型尚未安装；全文检索可直接使用。']:[]),
    ...(status.file_notice_count?[`有 ${status.file_notice_count} 份附件需要注意，下方展示前 ${status.file_notices.length} 份。`]:[]),
    ...status.file_notices.map(fileNotice)
  ];
  for (const text of warnings) {const item=document.createElement('li'); item.textContent=text; el('warnings').append(item);}
  const d=status.discovery;
  el('updates').textContent=d?`最近检查：${d.checked||'启动检查'}；新增 ${d.new||0} 篇，更新 ${d.updated||0} 篇。${d.complete?'':'部分来源失败：'+(d.errors||[]).join('；')} 《社会学研究》《中国人口科学》只检查当期，长期未运行可能漏期；官网目录不含目录之外的网络首发文章。`:'尚未运行期刊更新。待接入来源不会自动发出网络请求。';
}
for (const [id,path,label] of [['import','/api/import','导入'],['embed','/api/embed','构建索引'],['discover','/api/discover','期刊更新']]) {
  el(id).onclick=async()=>{
    document.querySelectorAll('.toolbar button').forEach(button=>button.disabled=true); notice(label+'进行中，请保持本页面和 Zotero 打开…');
    try {const result=await api(path); notice(label+'完成。'+(result.items_changed!==undefined?`条目变化 ${result.items_changed}，PDF 重建 ${result.files_indexed}，PDF 未变化 ${result.files_unchanged}。`:'')+(result.complete===false?' 部分来源失败，请查看下方提示。':'')); await refresh();}
    catch(error){notice(error.message,true);} finally{document.querySelectorAll('.toolbar button').forEach(button=>button.disabled=false);}
  };
}
el('search').onsubmit=async event=>{
  event.preventDefault(); notice('检索中…'); el('results').replaceChildren();
  try {
    const rows=await api('/api/search',{query:el('query').value,mode:el('mode').value}); notice(`找到 ${rows.length} 条结果（最多显示 20 条）。`+(el('mode').value==='semantic'&&semanticScope?` 语义试点范围：${semanticScope}。`:''));
    for (const row of rows) {
      const box=document.createElement('article'); box.className='result';
      const type=document.createElement('small'); type.textContent=({pdf:'PDF 原文',metadata:'书目信息',note:'个人笔记'})[row.kind]||row.kind;
      if(row.page) type.textContent+=` · PDF 第 ${row.page} 页 · 文件页标签 ${row.page_label}`;
      const heading=document.createElement('h3'); heading.textContent=row.title; const paragraph=document.createElement('pre'); paragraph.textContent=row.text; box.append(type,heading,paragraph);
      if(row.pdf_url){const link=document.createElement('a'); link.href=row.pdf_url; link.target='_blank'; link.rel='noopener'; link.textContent='打开 PDF 对应页 ↗'; box.append(link);}
      el('results').append(box);
    }
  } catch(error){notice(error.message,true);}
};
refresh().then(()=>notice('本地资料库已就绪。')).catch(error=>notice(error.message,true));
setInterval(()=>{if(!document.hidden) refresh().catch(()=>{});},15000);
