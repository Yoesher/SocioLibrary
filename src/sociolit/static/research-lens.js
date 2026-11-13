/* Research lenses guide examples and evidence review; they never filter the library. */
(() => {
  let catalog = null, loading = false, saving = false;
  const make = (tag, text = '', cls = '') => {
    const node = document.createElement(tag); node.textContent = text; node.className = cls; return node;
  };
  window.isResearchProfileBusy = () => saving;
  function render() {
    const profile = catalog.profiles.find(row => row.id === catalog.current);
    el('research-profile').replaceChildren();
    for (const row of catalog.profiles) {
      const option = make('option', row.name); option.value = row.id; el('research-profile').append(option);
    }
    el('research-profile').value = profile.id; el('research-profile').disabled = false;
    el('research-focus').textContent = profile.focus;
    el('research-profile-state').textContent = catalog.message;
    el('research-examples').replaceChildren();
    for (const example of profile.examples) {
      const button = make('button', example, 'research-example'); button.type = 'button';
      button.onclick = () => {
        el('query').value = example; el('query').focus();
        notice('已填入研究问题。点击“检索”查找本机文献。');
      };
      el('research-examples').append(button);
    }
    el('query').placeholder = '输入关键词或研究问题，如：' + profile.examples[0];
    el('research-journal').hidden = !profile.journal;
    el('research-journal').textContent = profile.journal ? '准备订阅：' + profile.journal.name : '';
    document.querySelectorAll('.research-current').forEach(node => {node.textContent = '研究视角：' + profile.name;});
  }
  window.loadResearchLens = async () => {
    if (!token || catalog || loading) return;
    loading = true;
    try {
      const response = await fetch('/api/research/profile', {headers: {'X-Sociolit-Token': token}});
      const value = await response.json();
      if (!response.ok) throw new Error(value.detail || '读取研究视角失败');
      catalog = value; render();
    } catch (error) {el('research-profile-state').textContent = error.message;}
    finally {loading = false;}
  };
  el('research-profile').onchange = async () => {
    if (!catalog || saving) return;
    const identity = el('research-profile').value;
    if (window.isAIBusy?.() || window.isLiteratureBusy?.()) {
      el('research-profile').value = catalog.current; notice('请等待当前阅读或比较任务完成。', true); return;
    }
    saving = true; el('research-profile').disabled = true;
    try {
      catalog = await api('/api/research/profile', {identity}); render();
      document.dispatchEvent(new CustomEvent('researchprofilechange'));
      notice('研究视角已保存。原有文献、索引范围和订阅继续沿用。');
    } catch (error) {el('research-profile').value = catalog.current; notice(error.message, true);}
    finally {saving = false; el('research-profile').disabled = false;}
  };
  el('research-journal').onclick = () => {
    const profile = catalog?.profiles.find(row => row.id === catalog.current);
    if (profile?.journal) window.prepareResearchJournal?.(profile.journal);
  };
  const tasks = {
    methods: '请判断所选材料的研究类型，审读其材料、概念或测量、方法与论证，并区分已有依据和还需要补读之处。',
    evidence_map: '请围绕当前研究问题，按概念和命题组织所选材料的证据、分歧与适用范围。每项标注来源，列出待核查之处。',
    review_outline: '请按问题和分歧组织所选材料，形成文献综述提纲；每一节列出来源和待补读材料，不替材料补造结论。'
  };
  for (const button of document.querySelectorAll('[data-research-task]')) button.onclick = () => {
    const task = button.dataset.researchTask;
    showView('ai-view'); el('ai-task').value = task;
    el('ai-question').value = (el('query').value.trim() ? '研究问题：' + el('query').value.trim() + '\n' : '') + tasks[task];
    el('ai-task').dispatchEvent(new Event('input', {bubbles: true}));
    document.dispatchEvent(new CustomEvent('airesearchtask'));
    notice('阅读任务已准备。先在检索结果中选择片段，再预览本次发送内容。');
  };
  if (token) window.loadResearchLens();
})();
