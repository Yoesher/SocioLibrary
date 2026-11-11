(() => {
  const states = {to_read: '待读', reading: '在读', done: '已读'};
  const modes = {fulltext: '全文检索', semantic: '语义检索', hybrid: '混合检索'};
  const controls = new Map();
  let libraryStatus = null, updateState = null, updateContext = null;
  let installIntent = false, installing = false, noteDirty = false, exporting = false;

  window.resetReadingControls = () => controls.clear();
  function setReadingControls(itemId, state) {
    for (const pair of controls.get(itemId) || []) {
      pair.select.value = state.status || '';
      pair.star.textContent = state.favorite ? '★ 已收藏' : '☆ 收藏';
      pair.state.status = state.status;
      pair.state.favorite = state.favorite;
    }
  }
  window.enhanceReadingResult = (box, row) => {
    const state = {...row.reading};
    const toolbar = document.createElement('div'); toolbar.className = 'toolbar reading-controls';
    const select = document.createElement('select'); select.setAttribute('aria-label', '设置阅读状态');
    for (const [value, title] of Object.entries({'': '加入阅读清单', ...states})) {
      const option = document.createElement('option'); option.value = value; option.textContent = title; select.append(option);
    }
    const star = document.createElement('button'); star.className = 'secondary';
    const pairs = controls.get(row.item_id) || []; pairs.push({select, star, state}); controls.set(row.item_id, pairs);
    setReadingControls(row.item_id, state);
    async function save(status, favorite) {
      try {
        await api('/api/research/reading', {item_id: row.item_id, status, favorite});
        setReadingControls(row.item_id, {status, favorite}); notice('阅读清单已保存到本机。');
      } catch (error) { notice(error.message, true); setReadingControls(row.item_id, state); }
    }
    select.onchange = () => select.value && save(select.value, Boolean(state.favorite));
    star.onclick = () => save(state.status || 'to_read', !state.favorite);
    toolbar.append(select, star); box.append(toolbar);
  };

  async function readApi(path) {
    const response = await fetch(path, {headers: {'X-Sociolit-Token': token}});
    if (!response.ok) throw new Error('读取本机阅读资料失败');
    return response.json();
  }
  async function loadReading() {
    try {
      const parameters = new URLSearchParams({status: el('reading-filter').value,
        favorite: el('reading-favorites').checked, archived: el('reading-archived').checked});
      const rows = await readApi('/api/research/reading?' + parameters);
      el('reading-list').replaceChildren();
      if (!rows.length) {
        const empty = document.createElement('p'); empty.className = 'hint';
        empty.textContent = '这里还没有符合条件的文献。可在检索结果中加入清单，或切换筛选条件。'; el('reading-list').append(empty);
      }
      for (const row of rows) {
        const box = document.createElement('article'); box.className = 'result';
        const title = document.createElement('h3'); title.textContent = row.title;
        const detail = document.createElement('p'); detail.className = 'hint';
        detail.textContent = [states[row.status], row.favorite ? '已收藏' : '',
          (row.metadata.authors || []).join('、'), row.metadata.year || '',
          row.available ? '' : '原条目已移出文献库，清单快照仍保留'].filter(Boolean).join(' · ');
        const actions = document.createElement('div'); actions.className = 'toolbar';
        const select = document.createElement('select'); select.setAttribute('aria-label', '阅读状态');
        for (const [value, label] of Object.entries(states)) {
          const option = document.createElement('option'); option.value = value; option.textContent = label; select.append(option);
        }
        select.value = row.status;
        async function save(changes) {
          try { await api('/api/research/reading', {item_id: row.item_id, status: row.status,
            favorite: row.favorite, archived: row.archived, ...changes}); await loadReading(); }
          catch (error) { notice(error.message, true); }
        }
        select.onchange = () => save({status: select.value});
        const star = document.createElement('button'); star.className = 'secondary';
        star.textContent = row.favorite ? '取消收藏' : '收藏'; star.onclick = () => save({favorite: !row.favorite});
        const find = document.createElement('button'); find.className = 'secondary'; find.textContent = '检索本文';
        find.disabled = !row.available; find.onclick = () => {
          el('query').value = row.title.slice(0, 500); el('mode').value = 'fulltext';
          el('author').value = ''; el('year').value = ''; showView('search-view'); el('search').requestSubmit();
        };
        const archive = document.createElement('button'); archive.className = 'secondary';
        archive.textContent = row.archived ? '恢复到清单' : '归档'; archive.onclick = () => save({archived: !row.archived});
        actions.append(select, star, find, archive); box.append(title, detail, actions); el('reading-list').append(box);
      }
    } catch (error) { notice(error.message, true); }
  }
  for (const id of ['reading-filter', 'reading-favorites', 'reading-archived']) el(id).onchange = loadReading;
  document.querySelector('[data-view="reading-view"]').addEventListener('click', loadReading);

  async function loadRecent() {
    try {
      const records = await readApi('/api/research/recent'); el('recent-searches').replaceChildren();
      for (const query of records) {
        const button = document.createElement('button'); button.className = 'secondary recent-query';
        button.textContent = [query.query, modes[query.mode], query.author, query.year].filter(Boolean).join(' · ');
        button.onclick = () => { for (const key of ['query', 'mode', 'author', 'year']) el(key).value = query[key] || '';
          showView('search-view'); el('search').requestSubmit(); };
        el('recent-searches').append(button);
      }
      if (!records.length) el('recent-searches').textContent = '还没有最近检索。';
    } catch (error) { notice(error.message, true); }
  }
  document.querySelector('[data-view="research-view"]').addEventListener('click', loadRecent);
  el('clear-recent').onclick = async () => {
    try { await api('/api/research/recent/clear'); await loadRecent(); notice('最近检索已清空；保存的检索和笔记继续保留。'); }
    catch (error) { notice(error.message, true); }
  };
  for (const id of ['note-title', 'note-body']) el(id).addEventListener('input', () => {noteDirty = true;});
  el('new-note').addEventListener('click', () => {noteDirty = false;});

  function preferencesDirty() {
    if (!libraryStatus || !settingsLoaded) return false;
    const normalize = root => root.trim().replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase();
    const roots = el('roots').value.split(/\r?\n/).filter(x => x.trim()).map(normalize);
    const keywords = el('keywords').value.split(/[,，、]/).map(x => x.trim()).filter(Boolean);
    return JSON.stringify(roots) !== JSON.stringify((libraryStatus.pdf_roots || []).map(normalize)) ||
      JSON.stringify(keywords) !== JSON.stringify(libraryStatus.collection_keywords || []);
  }
  async function attachNative() {
    const bridge = window.pywebview && window.pywebview.api;
    if (!bridge) return;
    try { updateContext = await bridge.update_context(); }
    catch (_) { updateContext = {supported: false, mode: 'source', message: '当前桌面组件无法启动一键安装，请重新打开软件。'}; }
    el('export-notes').hidden = false;
    el('software-open-cache').hidden = false;
    el('software-open-cache').onclick = async () => {
      try { await bridge.open_update_folder(); } catch (error) { notice('无法打开更新记录：' + error.message, true); }
    };
    el('export-notes').onclick = async () => {
      exporting = true;
      try {
        const result = await bridge.export_notes();
        if (result.saved) notice('全部未归档笔记和摘录已导出到你选择的本机文件。');
      } catch (error) { notice('导出未完成：' + error.message, true); }
      finally { exporting = false; }
    };
    if (libraryStatus) window.renderSoftwareUpdate(libraryStatus);
  }
  window.addEventListener('pywebviewready', attachNative); attachNative();

  async function installReady() {
    if (installing || !updateContext || !updateContext.supported) return;
    if (exporting || noteDirty || preferencesDirty() || searchBusy || (window.isAIBusy && window.isAIBusy()) || (window.isLiteratureBusy && window.isLiteratureBusy()) ||
        (window.isGraphBusy && window.isGraphBusy()) || (window.isGraphDirty && window.isGraphDirty()) || (window.isAppearanceDirty && window.isAppearanceDirty()) || (window.isAISettingsDirty && window.isAISettingsDirty()) || (window.isLiteratureDirty && window.isLiteratureDirty()) || libraryStatus.library_busy ||
        libraryStatus.job.state === 'running') {
      el('software-progress-text').textContent = '更新包已就绪，等待保存笔记和设置、结束当前任务；也可选择稍后安装。';
      return;
    }
    installing = true; el('software-upgrade').disabled = true;
    const editable = [...document.querySelectorAll('main button, input, select, textarea')].filter(node => !node.disabled);
    editable.forEach(node => {node.disabled = true;});
    el('software-status').textContent = '正在准备安装，将关闭软件并自动重新打开原资料库…';
    try { await window.pywebview.api.install_update(); }
    catch (error) { installing = false; installIntent = false; editable.forEach(node => {node.disabled = false;});
      notice('尚未开始安装：' + error.message, true); }
  }
  async function beginUpgrade() {
    showView('software-view');
    if (noteDirty || preferencesDirty() || (window.isGraphBusy && window.isGraphBusy()) || (window.isGraphDirty && window.isGraphDirty()) || (window.isAppearanceDirty && window.isAppearanceDirty()) || (window.isAISettingsDirty && window.isAISettingsDirty()) || (window.isLiteratureDirty && window.isLiteratureDirty())) { notice('请先保存笔记、对照表、资料与 AI 设置，并处理对照篮或草稿，再开始升级。', true); return; }
    if (!updateState || !updateState.available_version) return;
    installIntent = Boolean(updateContext && updateContext.supported);
    if (updateState.state === 'ready') { await installReady(); return; }
    try { await api('/api/software-update/download'); await refresh(); }
    catch (error) { installIntent = false; notice(error.message, true); }
  }
  el('software-upgrade').onclick = beginUpgrade;
  el('software-banner-go').onclick = () => {
    if (updateContext && updateContext.mode === 'installed') beginUpgrade();
    else showView('software-view');
  };
  el('software-later').onclick = () => {installIntent = false; el('software-later').hidden = true;
    notice('将保留下载包，等你点击“安装并重启”再升级。');};
  el('software-check').onclick = async () => {
    try { await api('/api/software-update/check'); await refresh(); }
    catch (error) { notice(error.message, true); }
  };
  el('software-auto').onchange = async () => {
    try { await api('/api/software-update/automatic', {enabled: el('software-auto').checked}); await refresh(); }
    catch (error) { notice(error.message, true); }
  };
  el('release-page').onclick = () => showView('software-view');
  window.isSoftwareInstalling = () => installing;
  document.addEventListener('click', event => {
    if (installing) { event.preventDefault(); event.stopImmediatePropagation(); }
  }, true);

  window.renderSoftwareUpdate = status => {
    libraryStatus = status; updateState = status.software_update;
    if (!updateState || installing) return;
    const s = updateState, busy = ['checking', 'downloading'].includes(s.state);
    const available = Boolean(s.available_version);
    const labels = {idle: '当前版本 ' + s.current_version + '；可手动检查更新。', checking: '正在检查官方正式版本…',
      current: '当前版本 ' + s.current_version + '；暂无可用的新正式版本。',
      available: '发现新版本 ' + s.available_version + '，当前版本 ' + s.current_version + '。',
      downloading: '正在下载 ' + s.available_version + '，可以继续检索或选择稍后安装。',
      ready: '更新包已完成下载和文件核对，可以安装。', error: s.error};
    el('software-status').textContent = labels[s.state] || s.state;
    el('software-last-result').textContent = s.last_install || '';
    el('software-auto').checked = s.auto_check;
    el('software-check').disabled = busy;
    el('software-upgrade').disabled = busy || !available;
    el('software-upgrade').textContent = s.state === 'ready' ? '安装并重启' :
      updateContext && updateContext.mode === 'portable' ? '下载并升级为安装版' : '下载并升级';
    if (!updateContext || !updateContext.supported) {
      el('software-upgrade').textContent = s.state === 'ready' ? '更新包已下载' : '下载更新包';
      if (s.state === 'ready') el('software-upgrade').disabled = true;
    }
    el('software-native-message').textContent = updateContext ? updateContext.message : '桌面发布版支持一键安装；浏览器页面可检查与下载。';
    el('software-notes').textContent = s.notes || '暂无新版本说明。';
    el('software-progress').hidden = !s.total;
    if (s.total) { el('software-progress').max = s.total; el('software-progress').value = s.downloaded; }
    el('software-progress-text').textContent = s.total ?
      (s.downloaded / 1048576).toFixed(1) + ' / ' + (s.total / 1048576).toFixed(1) + ' MB' : '';
    el('software-later').hidden = !installIntent;
    el('software-banner').hidden = !available;
    el('software-banner-text').textContent = '发现新版本 ' + s.available_version + '；升级后自动沿用原库与设置。';
    el('software-banner-go').disabled = busy;
    if (s.state === 'error') installIntent = false;
    if (s.state === 'ready' && installIntent) installReady();
  };
})();
