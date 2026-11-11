(() => {
  const selected = new Map(), selectionControls = new Map();
  let profiles = [], presets = [], preview = null, answer = null, busy = false, dirty = false;
  window.isAIBusy = () => busy;
  window.isAISettingsDirty = () => dirty;
  const types = {pdf: 'PDF 原文', ocr: 'OCR 文字（需核对）', metadata: '书目信息', note: '个人笔记', annotation: 'Zotero 摘录与个人批注'};
  function invalidate() {preview = null; el('ai-preview').hidden = true; el('ai-consent').checked = false;}
  function updateSelection() {
    invalidate(); el('ai-selected').replaceChildren();
    el('ai-selection-count').textContent = `已选 ${selected.size} / 8 个片段；选择本身不会发送资料。`;
    for (const [id, source] of selected) {
      const line = document.createElement('div'); line.className = 'ai-selection';
      const label = document.createElement('span');
      label.textContent = source.title + (source.page ? ` · PDF 第 ${source.page} 页` : ' · 无 PDF 页码');
      const remove = document.createElement('button'); remove.className = 'text-button'; remove.textContent = '移除';
      remove.onclick = () => {selected.delete(id); updateSelection();}; line.append(label, remove); el('ai-selected').append(line);
    }
    for (const [id, controls] of selectionControls) for (const box of controls) box.checked = selected.has(id);
  }
  window.resetAIControls = () => selectionControls.clear();
  window.openOrganizingTask = () => {showView('ai-view');el('ai-task').value='organize';el('ai-question').value='请按文献分别整理主题标签、研究问题、理论、方法和对象，给出片段出处；缺少依据写材料未提供。只生成待核对建议。';invalidate();loadProfiles();};
  window.enhanceAIResult = (box, source) => {
    const label = document.createElement('label'); label.className = 'inline-label ai-source-select';
    const check = document.createElement('input'); check.type = 'checkbox'; check.checked = selected.has(source.id);
    if (!selectionControls.has(source.id)) selectionControls.set(source.id, []);
    selectionControls.get(source.id).push(check);
    check.onchange = () => {
      if (check.checked && selected.size >= 8 && !selected.has(source.id)) {
        check.checked = false; notice('每次最多选择 8 个片段，可先在 AI 阅读中移除部分片段。', true); return;
      }
      if (check.checked) selected.set(source.id, source); else selected.delete(source.id);
      updateSelection();
    };
    label.append(check, document.createTextNode('用于 AI 阅读或整理（发送前可预览）')); box.append(label);
  };
  async function loadProfiles(keep = '') {
    try {
      const response = await fetch('/api/ai/profiles', {headers: {'X-Sociolit-Token': token}});
      const data = await response.json(); if (!response.ok) throw new Error(data.detail);
      profiles = data.profiles; presets = data.presets;
      const current = keep || el('ai-connection').value;
      el('ai-connection').replaceChildren();
      for (const profile of profiles) {
        const option = document.createElement('option'); option.value = profile.id;
        option.textContent = profile.name + ' · ' + profile.model; el('ai-connection').append(option);
      }
      if (profiles.some(profile => profile.id === current)) el('ai-connection').value = current;
      if (!el('ai-preset').options.length) {
        for (const preset of presets) {
          const option = document.createElement('option'); option.value = preset.id;
          option.textContent = preset.name; el('ai-preset').append(option);
        }
        fillPreset(); dirty = false; el('ai-settings').open = !profiles.length;
      }
      el('ai-config-status').textContent = profiles.length ?
        `已保存 ${profiles.length} 个连接。保存、切换或修改配置不会自动调用 API。` : '尚未配置 AI；下方填写后即可使用。';
      invalidate();
    } catch (error) {el('ai-config-status').textContent = error.message;}
  }
  function setDirty() {dirty = true; invalidate();}
  function fillPreset() {
    const preset = presets.find(row => row.id === el('ai-preset').value); if (!preset) return;
    el('ai-name').value = preset.name; el('ai-base-url').value = preset.base_url;
    el('ai-protocol').value = preset.protocol; el('ai-model').value = preset.model;
    el('ai-key').value = ''; el('ai-clear-key').checked = false; setDirty();
    el('ai-token-parameter').value = 'auto'; el('ai-disable-thinking').checked = preset.id === 'qwen';
  }
  el('ai-preset').onchange = fillPreset;
  el('ai-connection').onchange = invalidate;
  el('ai-edit').onclick = () => {
    const profile = profiles.find(row => row.id === el('ai-connection').value); if (!profile) return;
    el('ai-profile-id').value = profile.id; el('ai-name').value = profile.name;
    el('ai-protocol').value = profile.protocol; el('ai-base-url').value = profile.base_url;
    el('ai-model').value = profile.model; el('ai-output-limit').value = profile.max_output_tokens;
    el('ai-key').value = ''; el('ai-clear-key').checked = false; dirty = false;
    el('ai-token-parameter').value = profile.token_parameter || 'auto';
    el('ai-disable-thinking').checked = Boolean(profile.disable_thinking);
    el('ai-key-state').textContent = profile.has_key ? '已加密保存密钥。留空沿用；修改地址或协议后须重新填写。' : '尚未保存密钥；本机服务可留空。';
    el('ai-settings').open = true;
  };
  el('ai-new').onclick = () => {el('ai-profile-id').value = ''; el('ai-output-limit').value = '2048';
    fillPreset(); el('ai-settings').open = true; el('ai-key-state').textContent = '新建连接；密钥保存在当前系统的受保护存储中。';};
  el('ai-discard').onclick = () => {el('ai-profile-id').value = ''; el('ai-key').value = '';
    dirty = false; el('ai-settings').open = false; notice('已放弃未保存的 AI 配置。');};
  for (const id of ['ai-name', 'ai-protocol', 'ai-base-url', 'ai-model', 'ai-output-limit', 'ai-key', 'ai-clear-key',
                    'ai-token-parameter', 'ai-disable-thinking'])
    el(id).addEventListener('input', setDirty);
  el('ai-profile-form').onsubmit = async event => {
    event.preventDefault(); if (busy) return;
    const key = el('ai-key').value; el('ai-key').value = '';
    const body = {identity: el('ai-profile-id').value || null, name: el('ai-name').value,
      protocol: el('ai-protocol').value, base_url: el('ai-base-url').value, model: el('ai-model').value,
      max_output_tokens: Number(el('ai-output-limit').value), clear_key: el('ai-clear-key').checked};
    if (key.trim()) body.api_key = key;
    body.token_parameter = el('ai-token-parameter').value;
    body.disable_thinking = el('ai-disable-thinking').checked;
    busy = true;
    try {
      const saved = await api('/api/ai/profiles', body); dirty = false; el('ai-profile-id').value = saved.id;
      await loadProfiles(saved.id); el('ai-settings').open = false;
      notice('AI 连接已保存；尚未调用 API。密钥不会显示或写入公开项目。');
    } catch (error) {notice(error.message + ' 如需密钥，请重新填写。', true);}
    finally {busy = false;}
  };
  el('ai-delete').onclick = async () => {
    const identity = el('ai-connection').value; if (!identity || busy) return;
    if (!window.confirm('移除当前 AI 连接及其加密密钥？文献和笔记会继续保留。')) return;
    try {await api('/api/ai/delete', {identity}); await loadProfiles(); notice('该 AI 连接已移除。');}
    catch (error) {notice(error.message, true);}
  };
  async function working(action) {
    if (busy) return;
    if (dirty) {notice('请先保存或放弃正在编辑的 AI 配置。', true); return;}
    busy = true; const buttons = [...el('ai-view').querySelectorAll('button')].filter(button => !button.disabled);
    buttons.forEach(button => {button.disabled = true;});
    try {await action();} catch (error) {notice(error.message, true);}
    finally {busy = false; buttons.forEach(button => {button.disabled = false;});}
  }
  el('ai-test').onclick = () => working(async () => {
    if (!el('ai-test-consent').checked) {notice('请先确认固定短提示测试可能产生 API 费用。', true); return;}
    notice('正在发送固定短提示测试，不发送文献；最长等待约两分钟…');
    const result = await api('/api/ai/test', {identity: el('ai-connection').value, confirm_cost: true});
    notice('AI 请求已通过。' + (result.warning || '') + usageText(result.usage));
  });
  function usageText(usage) {
    return Object.keys(usage || {}).length ? ` 服务商报告：输入 ${usage.input_tokens ?? '未知'}，输出 ${usage.output_tokens ?? '未知'} tokens。` : ' 服务商未报告 token 用量。';
  }
  for (const id of ['ai-question', 'ai-task']) el(id).addEventListener('input', invalidate);
  el('ai-clear-selected').onclick = () => {selected.clear(); updateSelection();};
  el('ai-go-search').onclick = () => showView('search-view');
  el('ai-prepare').onclick = () => working(async () => {
    invalidate();
    preview = await api('/api/ai/preview', {identity: el('ai-connection').value,
      question: el('ai-question').value, task: el('ai-task').value,
      sources: [...selected.values()].map(row => ({chunk_id: row.id, digest: row.source_digest}))});
    el('ai-preview-destination').textContent = `${preview.name} · ${preview.model} · ${preview.base_url}`;
    el('ai-preview-size').textContent = `将发送 ${preview.sources.length} 个片段，提示文字共 ${preview.characters.toLocaleString()} 字符，最多输出 ${preview.max_output_tokens} tokens。字符数不等于 token 数，实际费用以服务商计费为准。`;
    el('ai-preview-sources').replaceChildren(); renderSources(el('ai-preview-sources'), preview.sources);
    el('ai-full-prompt').textContent = '系统提示：\n' + preview.system + '\n\n输入：\n' + preview.prompt;
    el('ai-consent-label').textContent = preview.local ? '确认把本次问题与片段发送给上方本机服务，并了解其配置可能继续调用云端。' : '确认向上方服务商发送本次问题、所选片段和书目信息；我有权发送，且知悉可能产生 API 费用。';
    el('ai-preview').hidden = false; notice('预览已在本机生成；尚未发送到 AI。请核对接收地址及内容。');
  });
  function renderSources(container, sources) {
    for (const source of sources) {
      const box = document.createElement('article'); box.className = 'ai-evidence';
      const title = document.createElement('strong'); title.textContent = `[${source.label}] ${source.title}`;
      const detail = document.createElement('p'); detail.className = 'hint';
      detail.textContent = [source.authors, source.year, types[source.kind] || source.kind,
        source.page ? `PDF 第 ${source.page} 页（文件标签 ${source.page_label || '未提供'}）` : '无 PDF 页码',
        source.truncated ? '片段已截短' : ''].filter(Boolean).join(' · ');
      const text = document.createElement('pre'); text.className = 'changelog'; text.textContent = source.text;
      box.append(title, detail, text);
      if (source.pdf_url) {const link = document.createElement('a'); link.href = source.pdf_url;
        link.textContent = '回到原文对应页 ↗'; link.target = '_blank'; link.rel = 'noopener'; box.append(link);}
      container.append(box);
    }
  }
  el('ai-send').onclick = () => working(async () => {
    if (!preview || !el('ai-consent').checked) {notice('请预览并确认本次发送内容。', true); return;}
    const confirmation = preview.confirmation; invalidate();
    notice('AI 正在处理所选片段；不会自动重试，最长等待约两分钟…');
    answer = await api('/api/ai/ask', {confirmation, consent: true});
    el('ai-answer').hidden = false; el('ai-answer-text').textContent = answer.text;
    el('ai-answer-notices').textContent = answer.notices.join(' ') + usageText(answer.usage);
    el('ai-answer-sources').replaceChildren(); renderSources(el('ai-answer-sources'), answer.sources);
    el('ai-save-answer').disabled = false; notice('已生成 AI 草稿，请逐条对照原文核验；尚未保存为笔记。');
  });
  el('ai-save-answer').onclick = () => working(async () => {
    if (!answer) return; await api('/api/ai/save-draft', {identity: answer.id});
    notice('已保存为标明“AI 生成草稿”的本地阅读笔记，并附本次来源快照。');
  });
  el('ai-copy-answer').onclick = async () => {
    if (!answer) return;
    try {await navigator.clipboard.writeText('【AI 生成草稿，需人工核对】\n' + answer.text + '\n\n' +
      answer.sources.map(source => `[${source.label}] ${source.title} · ${source.page ? 'PDF 第 ' + source.page + ' 页' : '无 PDF 页码'}`).join('\n'));
      notice('已复制 AI 草稿及来源清单。');} catch (_) {notice('请手动选择答复文字复制。', true);}
  };
  document.querySelector('[data-view="ai-view"]').addEventListener('click', () => {
    if (!presets.length && token) loadProfiles();
  });
  window.addEventListener('beforeunload', () => {el('ai-key').value = '';});
  updateSelection();
})();
