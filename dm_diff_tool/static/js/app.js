// ---- State ----
let pyodide = null;
let manifest = null;
let currentDiff = null;
let lastParams = null;
const xmlCache = {};  // cache fetched XML: "version/clusters/file.xml" -> string

// ---- Base URL for data files ----
const BASE = new URL('.', window.location.href).href;

// ---- Load data manifest ----
async function loadManifest(status) {
  status.textContent = 'Loading data manifest...';
  const resp = await fetch(BASE + 'data_manifest.json');
  if (!resp.ok) {
    throw new Error(`Cannot load data_manifest.json (HTTP ${resp.status}). Run generate_manifest.py before serving.`);
  }
  return await resp.json();
}

// ---- Initialization ----
async function init() {
  const status = document.getElementById('initStatus');

  manifest = await loadManifest(status);

  // Populate version selects
  const versions = Object.keys(manifest);
  const oldSel = document.getElementById('oldVersion');
  const newSel = document.getElementById('newVersion');
  const oldDefault = versions.length >= 2 ? versions.length - 2 : 0;
  const newDefault = versions.length - 1;
  versions.forEach((v, i) => {
    oldSel.add(new Option(v, v, false, i === oldDefault));
    newSel.add(new Option(v, v, false, i === newDefault));
  });

  // Load Pyodide
  status.textContent = 'Loading Python runtime (Pyodide)...';
  pyodide = await loadPyodide();

  // Load diff engine
  status.textContent = 'Loading diff engine...';
  const engineResp = await fetch(BASE + 'diff_engine.py');
  const engineCode = await engineResp.text();
  pyodide.runPython(engineCode);

  // Ready
  document.getElementById('compareBtn').disabled = false;
  document.getElementById('initOverlay').style.display = 'none';
}

init().catch(err => {
  document.getElementById('initStatus').textContent = 'Failed to initialize: ' + err.message;
  console.error(err);
});

// ---- Fetch XML files for a version + category ----
async function fetchXmlMap(version, category) {
  const files = manifest[version][category] || [];
  const map = {};
  const fetches = files.map(async (fname) => {
    const cacheKey = `${version}/${category}/${fname}`;
    if (xmlCache[cacheKey]) {
      map[fname] = xmlCache[cacheKey];
      return;
    }
    const url = `${BASE}data_model/${version}/${category}/${fname}`;
    const resp = await fetch(url);
    if (resp.ok) {
      const text = await resp.text();
      xmlCache[cacheKey] = text;
      map[fname] = text;
    }
  });
  await Promise.all(fetches);
  return map;
}

// ---- Run diff via Pyodide ----
async function runDiff() {
  const oldVer = document.getElementById('oldVersion').value;
  const newVer = document.getElementById('newVersion').value;
  const category = document.getElementById('category').value;
  const nameFilter = document.getElementById('nameFilter').value;
  const btn = document.getElementById('compareBtn');

  btn.disabled = true;
  btn.textContent = 'Comparing...';
  document.getElementById('exportBtn').style.display = 'none';
  document.getElementById('resultArea').innerHTML = `
    <div class="loading"><div class="spinner"></div><div>Computing diff between ${oldVer} and ${newVer}...</div></div>`;

  try {
    lastParams = {old: oldVer, new: newVer, category, name: nameFilter};
    const result = {};

    const categories = [];
    if (category === 'all' || category === 'clusters') categories.push('clusters');
    if (category === 'all' || category === 'device_types') categories.push('device_types');

    const setLoading = (msg) => {
      const el = document.querySelector('.loading div:last-child');
      if (el) el.textContent = msg;
    };

    for (const cat of categories) {
      setLoading(`Fetching ${cat.replace('_', ' ')} XML files...`);

      const [oldMap, newMap] = await Promise.all([
        fetchXmlMap(oldVer, cat),
        fetchXmlMap(newVer, cat),
      ]);

      setLoading(`Computing ${cat.replace('_', ' ')} diff...`);

      // Pass data to Python via Pyodide
      const oldMapProxy = pyodide.toPy(oldMap);
      const newMapProxy = pyodide.toPy(newMap);
      const jsonResult = pyodide.globals.get('run_diff')(
        oldMapProxy, newMapProxy, category, nameFilter, cat
      );
      oldMapProxy.destroy();
      newMapProxy.destroy();

      result[cat] = JSON.parse(jsonResult);
    }

    currentDiff = result;
    renderDiff(oldVer, newVer);
    document.getElementById('exportBtn').style.display = '';
  } catch (e) {
    document.getElementById('resultArea').innerHTML = `<div class="empty-state">Error: ${e.message}</div>`;
    console.error(e);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Compare';
  }
}

// ---- Export ----
function exportJSON() {
  if (!currentDiff || !lastParams) return;
  const exportData = {
    meta: {
      base_version: lastParams.old,
      new_version: lastParams.new,
      category: lastParams.category,
      filter: lastParams.name || null,
    },
    ...currentDiff,
  };
  const jsonStr = JSON.stringify(exportData, null, 2);
  const blob = new Blob([jsonStr], {type: 'application/json'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  let filename = `matterdiff_${lastParams.old}_vs_${lastParams.new}`;
  if (lastParams.name) filename += `_${lastParams.name}`;
  filename += '.json';
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ---- Swap ----
function swapVersions() {
  const o = document.getElementById('oldVersion');
  const n = document.getElementById('newVersion');
  [o.value, n.value] = [n.value, o.value];
}

// ---- Rendering (unchanged from original) ----
function renderDiff(oldVer, newVer) {
  const area = document.getElementById('resultArea');
  if (!currentDiff) { area.innerHTML = '<div class="empty-state">No data</div>'; return; }

  const nameFilter = (lastParams && lastParams.name) ? lastParams.name.trim() : '';
  let isFocused = false;
  let isBroad = false;
  if (nameFilter) {
    for (const cat of ['clusters', 'device_types']) {
      const d = currentDiff[cat];
      if (d && d._focused === true) isFocused = true;
      if (d && d._focused === false) isBroad = true;
    }
  }

  let html = '';

  if (nameFilter && isFocused) {
    html += `<div class="search-info focused"><span class="info-icon">&#8942;</span>
      Showing element-level diff for <strong>"${esc(nameFilter)}"</strong> within matching clusters / device types</div>`;
  } else if (nameFilter && isBroad) {
    html += `<div class="search-info broad"><span class="info-icon">&#9432;</span>
      No exact element match for <strong>"${esc(nameFilter)}"</strong>. Showing related clusters / device types containing the term</div>`;
  }

  html += `<div class="summary" id="summaryBar"></div>`;

  const cats = [];
  if (currentDiff.clusters) cats.push(['clusters', 'Clusters']);
  if (currentDiff.device_types) cats.push(['device_types', 'Device Types']);

  if (cats.length > 1) {
    html += `<div class="tabs">`;
    cats.forEach(([key, label], i) => {
      const d = currentDiff[key];
      const count = Object.keys(d.added||{}).length + Object.keys(d.removed||{}).length + Object.keys(d.modified||{}).length;
      html += `<button class="tab ${i===0?'active':''}" onclick="switchTab('${key}', this)">${label}<span class="badge">${count}</span></button>`;
    });
    html += `</div>`;
  }

  cats.forEach(([key, label], i) => {
    html += `<div class="tab-content" id="tab-${key}" style="display:${i===0?'block':'none'}">`;
    html += renderCategoryDiff(currentDiff[key], key, oldVer, newVer);
    html += `</div>`;
  });

  area.innerHTML = html;
  updateSummary();
}

function getActiveCategory() {
  const visible = document.querySelector('.tab-content[style*="display: block"], .tab-content[style*="display:block"]');
  if (visible) return visible.id.replace('tab-', '');
  const only = document.querySelector('.tab-content');
  return only ? only.id.replace('tab-', '') : 'clusters';
}

function catLabel(catKey) {
  return catKey === 'clusters' ? 'Clusters' : 'Device Types';
}

function updateSummary() {
  const bar = document.getElementById('summaryBar');
  if (!bar || !currentDiff) return;
  const cat = getActiveCategory();
  const d = currentDiff[cat];
  if (!d) return;

  const label = catLabel(cat);
  const nAdded = Object.keys(d.added || {}).length;
  const nRemoved = Object.keys(d.removed || {}).length;
  const nModified = Object.keys(d.modified || {}).length;
  const nUnchanged = (d.unchanged || []).length;
  let nRevUp = 0, nNoRev = 0;
  for (const v of Object.values(d.modified || {})) {
    if ((v.changes || {}).revision) nRevUp++; else nNoRev++;
  }

  bar.innerHTML = `
    <div class="summary-card added"><div class="count">${nAdded}</div><div class="label">${label} Added</div></div>
    <div class="summary-card removed"><div class="count">${nRemoved}</div><div class="label">${label} Removed</div></div>
    <div class="summary-card modified"><div class="count">${nModified}</div><div class="label">${label} Modified</div><div style="font-size:11px;color:var(--text-dim);margin-top:2px">${nRevUp} rev updated &middot; ${nNoRev} no rev update</div></div>
    <div class="summary-card unchanged"><div class="count">${nUnchanged}</div><div class="label">${label} Unchanged</div></div>`;
}

function switchTab(key, btn) {
  document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
  document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-' + key).style.display = 'block';
  btn.classList.add('active');
  updateSummary();
}

function renderCategoryDiff(diff, catKey, oldVer, newVer) {
  if (!diff) return '';
  const added = diff.added || {};
  const removed = diff.removed || {};
  const modified = diff.modified || {};
  const unchanged = diff.unchanged || [];
  const isCluster = catKey === 'clusters';
  const label = isCluster ? 'Cluster' : 'Device Type';

  let html = `<button class="expand-all-btn" onclick="toggleAll(this, '${catKey}')">Expand All</button>`;

  if (Object.keys(added).length) {
    html += `<div class="diff-section"><div class="diff-group-title"><span class="dot added-dot"></span> Added ${label}s (${Object.keys(added).length})</div>`;
    for (const [file, data] of Object.entries(added)) {
      html += renderAddedCard(file, data, isCluster);
    }
    html += `</div>`;
  }

  if (Object.keys(removed).length) {
    html += `<div class="diff-section"><div class="diff-group-title"><span class="dot removed-dot"></span> Removed ${label}s (${Object.keys(removed).length})</div>`;
    for (const [file, data] of Object.entries(removed)) {
      html += renderRemovedCard(file, data, isCluster);
    }
    html += `</div>`;
  }

  if (Object.keys(modified).length) {
    const revUpdated = {};
    const noRevUpdate = {};
    for (const [file, data] of Object.entries(modified)) {
      const changes = data.changes || {};
      if ('revision' in changes) {
        revUpdated[file] = data;
      } else {
        noRevUpdate[file] = data;
      }
    }

    if (Object.keys(revUpdated).length) {
      html += `<div class="diff-section"><div class="diff-group-title"><span class="dot modified-dot"></span> Modified ${label}s — Revision Updated (${Object.keys(revUpdated).length})</div>`;
      for (const [file, data] of Object.entries(revUpdated)) {
        html += renderModifiedCard(file, data, isCluster, oldVer, newVer);
      }
      html += `</div>`;
    }

    if (Object.keys(noRevUpdate).length) {
      html += `<div class="diff-section"><div class="diff-group-title"><span class="dot norev-dot"></span> Modified ${label}s — No Revision Update (${Object.keys(noRevUpdate).length})</div>`;
      for (const [file, data] of Object.entries(noRevUpdate)) {
        html += renderModifiedCard(file, data, isCluster, oldVer, newVer, true);
      }
      html += `</div>`;
    }
  }

  if (unchanged.length) {
    html += `<div class="diff-section"><div class="diff-group-title" style="color:var(--unchanged-text)">Unchanged ${label}s (${unchanged.length})</div>`;
    html += `<div style="color:var(--unchanged-text);font-size:13px;padding:4px 0;">${unchanged.map(f => esc(f.replace('.xml',''))).join(', ')}</div>`;
    html += `</div>`;
  }

  if (!Object.keys(added).length && !Object.keys(removed).length && !Object.keys(modified).length && !unchanged.length) {
    html += `<div class="empty-state">No items found matching your filter.</div>`;
  }

  return html;
}

function renderAddedCard(file, data, isCluster) {
  const id = 'card-' + file.replace(/[^a-zA-Z0-9]/g, '_');
  let html = `<div class="diff-card added-card" id="${id}">
    <div class="diff-card-header" onclick="toggleCard('${id}')">
      <div><span class="name">${esc(data.name)}</span> <span style="color:var(--text-dim);font-size:12px">${esc(file)}</span></div>
      <div class="meta">
        <span class="badge-sm badge-added">+ NEW</span>
        <span style="font-size:12px">Rev ${esc(data.revision)}</span>
        <span class="chevron">&#9654;</span>
      </div>
    </div>
    <div class="diff-card-body">`;
  html += renderFullItem(data, isCluster, 'added');
  html += `</div></div>`;
  return html;
}

function renderRemovedCard(file, data, isCluster) {
  const id = 'card-' + file.replace(/[^a-zA-Z0-9]/g, '_');
  let html = `<div class="diff-card removed-card" id="${id}">
    <div class="diff-card-header" onclick="toggleCard('${id}')">
      <div><span class="name">${esc(data.name)}</span> <span style="color:var(--text-dim);font-size:12px">${esc(file)}</span></div>
      <div class="meta">
        <span class="badge-sm badge-removed">- REMOVED</span>
        <span style="font-size:12px">Rev ${esc(data.revision)}</span>
        <span class="chevron">&#9654;</span>
      </div>
    </div>
    <div class="diff-card-body">`;
  html += renderFullItem(data, isCluster, 'removed');
  html += `</div></div>`;
  return html;
}

function renderModifiedCard(file, data, isCluster, oldVer, newVer, noRev) {
  const id = 'card-' + file.replace(/[^a-zA-Z0-9]/g, '_');
  const changes = data.changes || {};
  const changeSections = Object.keys(changes).filter(k => k !== 'revision' && k !== 'revisions');
  const cardClass = noRev ? 'norev-card' : 'modified-card';
  const badgeClass = noRev ? 'badge-norev' : 'badge-modified';
  const badgeLabel = noRev ? '~ NO REV UPDATE' : '~ MODIFIED';

  let html = `<div class="diff-card ${cardClass}" id="${id}">
    <div class="diff-card-header" onclick="toggleCard('${id}')">
      <div><span class="name">${esc(data.name)}</span> <span style="color:var(--text-dim);font-size:12px">${esc(file)}</span></div>
      <div class="meta">
        <span class="badge-sm ${badgeClass}">${badgeLabel}</span>
        <span style="font-size:12px">${changeSections.length} section(s) changed</span>
        <span class="chevron">&#9654;</span>
      </div>
    </div>
    <div class="diff-card-body">`;

  if (changes.revision) {
    html += `<div class="kv-change"><span class="kv-key">Revision:</span>
      <span class="val-old">${esc(String(changes.revision.old || ''))}</span>
      <span class="arrow">&rarr;</span>
      <span class="val-new">${esc(String(changes.revision.new || ''))}</span></div>`;
  }

  if (changes.revisions) {
    html += renderRevisionsDiff(changes.revisions);
  }

  if (changes.classification) {
    html += `<div class="detail-section"><div class="detail-section-title">Classification</div>`;
    if (Array.isArray(changes.classification)) {
      html += renderFieldChanges(changes.classification);
    }
    html += `</div>`;
  }

  if (changes.features) {
    html += renderSectionDiff('Features', changes.features, ['bit', 'code', 'name', 'summary', 'conformance']);
  }

  if (changes.dataTypes) {
    html += renderDataTypesDiff(changes.dataTypes);
  }

  if (changes.attributes) {
    html += renderSectionDiff('Attributes', changes.attributes, ['id', 'name', 'type', 'conformance', 'access', 'quality', 'constraint']);
  }

  if (changes.commands) {
    html += renderSectionDiff('Commands', changes.commands, ['id', 'name', 'direction', 'response', 'conformance', 'access']);
  }

  if (changes.events) {
    html += renderSectionDiff('Events', changes.events, ['id', 'name', 'priority', 'conformance', 'access']);
  }

  if (changes.conditionRequirements) {
    html += renderConditionRequirementsDiff(changes.conditionRequirements);
  }

  if (changes.clusters) {
    html += renderDeviceTypeClustersDiff(changes.clusters);
  }

  if (changes.conditions) {
    html += renderSectionDiff('Conditions', changes.conditions, ['name', 'summary']);
  }

  html += `</div></div>`;
  return html;
}

function renderRevisionsDiff(revDiff) {
  let html = `<div class="detail-section"><div class="detail-section-title">Revision History</div>`;
  if (revDiff.added && revDiff.added.length) {
    html += `<table class="detail-table"><thead><tr><th>Rev</th><th>Summary</th><th>Status</th></tr></thead><tbody>`;
    for (const r of revDiff.added) {
      html += `<tr class="row-added"><td>${esc(r.revision)}</td><td>${esc(r.summary)}</td><td><span class="badge-sm badge-added">NEW</span></td></tr>`;
    }
    html += `</tbody></table>`;
  }
  if (revDiff.modified && revDiff.modified.length) {
    html += `<table class="detail-table"><thead><tr><th>Rev</th><th>Field</th><th>Change</th></tr></thead><tbody>`;
    for (const m of revDiff.modified) {
      for (const c of m.changes) {
        html += `<tr class="row-modified"><td>${esc(m.key)}</td><td>${esc(c.field)}</td>
          <td><span class="val-old">${esc(String(c.old))}</span><span class="arrow">&rarr;</span><span class="val-new">${esc(String(c.new))}</span></td></tr>`;
      }
    }
    html += `</tbody></table>`;
  }
  html += `</div>`;
  return html;
}

function renderSectionDiff(title, diff, columns) {
  let html = `<div class="detail-section"><div class="detail-section-title">${title}</div>`;
  const added = diff.added || {};
  const removed = diff.removed || {};
  const modified = diff.modified || {};

  const hasContent = Object.keys(added).length || Object.keys(removed).length || Object.keys(modified).length;
  if (!hasContent) { html += `</div>`; return html; }

  html += `<table class="detail-table"><thead><tr>`;
  for (const col of columns) {
    html += `<th>${esc(col)}</th>`;
  }
  html += `<th>Status</th></tr></thead><tbody>`;

  for (const [key, item] of Object.entries(added)) {
    html += `<tr class="row-added">`;
    for (const col of columns) {
      const v = item[col];
      html += `<td>${esc(formatVal(v))}</td>`;
    }
    html += `<td><span class="badge-sm badge-added">ADDED</span></td></tr>`;
  }

  for (const [key, item] of Object.entries(removed)) {
    html += `<tr class="row-removed">`;
    for (const col of columns) {
      const v = item[col];
      html += `<td>${esc(formatVal(v))}</td>`;
    }
    html += `<td><span class="badge-sm badge-removed">REMOVED</span></td></tr>`;
  }

  for (const [key, mdata] of Object.entries(modified)) {
    const hasNewFormat = mdata && '_changes' in mdata;
    const changes = hasNewFormat ? mdata._changes : mdata;
    const baseItem = hasNewFormat ? (mdata._new || {}) : {};

    html += `<tr class="row-modified">`;
    const changeMap = {};
    if (changes && typeof changes === 'object') {
      for (const [field, change] of Object.entries(changes)) {
        if (change && typeof change === 'object' && 'old' in change && 'new' in change) {
          changeMap[field] = change;
        } else if (Array.isArray(change)) {
          changeMap[field] = {old: '(changed)', new: '(changed)'};
        } else if (change && typeof change === 'object' && ('added' in change || 'removed' in change || 'modified' in change)) {
          changeMap[field] = {old: '(sub-items changed)', new: '(sub-items changed)'};
        }
      }
    }
    for (const col of columns) {
      if (changeMap[col]) {
        html += `<td><span class="val-old">${esc(formatVal(changeMap[col].old))}</span>
          <span class="arrow">&rarr;</span>
          <span class="val-new">${esc(formatVal(changeMap[col].new))}</span></td>`;
      } else {
        const val = baseItem[col];
        html += `<td>${esc(formatVal(val !== undefined ? val : key))}</td>`;
      }
    }
    html += `<td><span class="badge-sm badge-modified">MODIFIED</span></td></tr>`;

    for (const [field, change] of Object.entries(changes || {})) {
      if (change && typeof change === 'object' && ('added' in change || 'removed' in change || 'modified' in change) && field === 'fields') {
        html += renderNestedFieldsDiff(key, change, columns.length + 1);
      }
    }
  }

  html += `</tbody></table></div>`;
  return html;
}

function renderNestedFieldsDiff(parentKey, fieldsDiff, colspan) {
  let html = '';
  const fieldCols = ['id', 'name', 'type', 'conformance', 'constraint'];

  if (fieldsDiff.added && fieldsDiff.added.length) {
    for (const f of fieldsDiff.added) {
      html += `<tr class="row-added"><td colspan="${colspan}" style="padding-left:32px">`;
      html += `<span class="badge-sm badge-added" style="margin-right:8px">+ FIELD</span>`;
      html += fieldCols.map(c => `<strong>${c}:</strong> ${esc(formatVal(f[c]))}`).join(' &middot; ');
      html += `</td></tr>`;
    }
  }
  if (fieldsDiff.removed && fieldsDiff.removed.length) {
    for (const f of fieldsDiff.removed) {
      html += `<tr class="row-removed"><td colspan="${colspan}" style="padding-left:32px">`;
      html += `<span class="badge-sm badge-removed" style="margin-right:8px">- FIELD</span>`;
      html += fieldCols.map(c => `<strong>${c}:</strong> ${esc(formatVal(f[c]))}`).join(' &middot; ');
      html += `</td></tr>`;
    }
  }
  if (fieldsDiff.modified && fieldsDiff.modified.length) {
    for (const m of fieldsDiff.modified) {
      html += `<tr class="row-modified"><td colspan="${colspan}" style="padding-left:32px">`;
      html += `<span class="badge-sm badge-modified" style="margin-right:8px">~ FIELD ${esc(m.key)}</span> `;
      for (const c of m.changes) {
        html += `<strong>${esc(c.field)}:</strong> <span class="val-old">${esc(String(c.old))}</span><span class="arrow">&rarr;</span><span class="val-new">${esc(String(c.new))}</span> &middot; `;
      }
      html += `</td></tr>`;
    }
  }
  return html;
}

function renderDataTypesDiff(diff) {
  let html = `<div class="detail-section"><div class="detail-section-title">Data Types</div>`;
  const added = diff.added || {};
  const removed = diff.removed || {};
  const modified = diff.modified || {};

  for (const [key, item] of Object.entries(added)) {
    html += `<div style="margin:6px 0;padding:8px;background:var(--added-bg);border-radius:4px;border:1px solid var(--added-border)">`;
    html += `<span class="badge-sm badge-added">ADDED</span> <strong>${esc(item.kind)}: ${esc(item.name)}</strong>`;
    html += renderDataTypeDetail(item, 'added');
    html += `</div>`;
  }

  for (const [key, item] of Object.entries(removed)) {
    html += `<div style="margin:6px 0;padding:8px;background:var(--removed-bg);border-radius:4px;border:1px solid var(--removed-border)">`;
    html += `<span class="badge-sm badge-removed">REMOVED</span> <strong>${esc(item.kind)}: ${esc(item.name)}</strong>`;
    html += renderDataTypeDetail(item, 'removed');
    html += `</div>`;
  }

  for (const [key, mdata] of Object.entries(modified)) {
    const hasNewFormat = mdata && '_changes' in mdata;
    const changes = hasNewFormat ? mdata._changes : mdata;
    const newItem = hasNewFormat ? (mdata._new || {}) : {};
    const displayName = newItem.name || key;
    const displayKind = newItem.kind || '';

    html += `<div style="margin:6px 0;padding:8px;background:var(--modified-bg);border-radius:4px;border:1px solid var(--modified-border)">`;
    html += `<span class="badge-sm badge-modified">MODIFIED</span> <strong>${displayKind ? esc(displayKind) + ': ' : ''}${esc(displayName)}</strong>`;
    for (const [field, change] of Object.entries(changes || {})) {
      if (field === 'items' || field === 'fields') {
        html += renderDataTypeItemsDiff(change);
      } else if (change && typeof change === 'object' && 'old' in change) {
        html += `<div class="kv-change"><span class="kv-key">${esc(field)}:</span>
          <span class="val-old">${esc(formatVal(change.old))}</span>
          <span class="arrow">&rarr;</span>
          <span class="val-new">${esc(formatVal(change.new))}</span></div>`;
      }
    }
    html += `</div>`;
  }

  html += `</div>`;
  return html;
}

function renderDataTypeDetail(item, type) {
  let html = '';
  const items = item.items || item.fields || [];
  if (items.length) {
    html += `<table class="detail-table" style="margin-top:6px"><tbody>`;
    for (const it of items) {
      const cls = type === 'added' ? 'row-added' : 'row-removed';
      html += `<tr class="${cls}">`;
      for (const k of Object.keys(it)) {
        html += `<td><span style="color:var(--text-dim);font-size:11px">${esc(k)}:</span> ${esc(formatVal(it[k]))}</td>`;
      }
      html += `</tr>`;
    }
    html += `</tbody></table>`;
  }
  return html;
}

function renderDataTypeItemsDiff(diff) {
  let html = '';
  if (diff.added && diff.added.length) {
    html += `<div style="margin-top:4px">`;
    for (const item of diff.added) {
      html += `<div style="padding:2px 0"><span class="badge-sm badge-added">+</span> `;
      html += Object.entries(item).map(([k,v]) => `<strong>${esc(k)}</strong>=${esc(formatVal(v))}`).join(' ');
      html += `</div>`;
    }
    html += `</div>`;
  }
  if (diff.removed && diff.removed.length) {
    html += `<div style="margin-top:4px">`;
    for (const item of diff.removed) {
      html += `<div style="padding:2px 0"><span class="badge-sm badge-removed">-</span> `;
      html += Object.entries(item).map(([k,v]) => `<strong>${esc(k)}</strong>=${esc(formatVal(v))}`).join(' ');
      html += `</div>`;
    }
    html += `</div>`;
  }
  if (diff.modified && diff.modified.length) {
    html += `<div style="margin-top:4px">`;
    for (const m of diff.modified) {
      html += `<div style="padding:2px 0"><span class="badge-sm badge-modified">~</span> <strong>${esc(m.key)}</strong>: `;
      for (const c of m.changes) {
        html += `${esc(c.field)}: <span class="val-old">${esc(String(c.old))}</span><span class="arrow">&rarr;</span><span class="val-new">${esc(String(c.new))}</span> `;
      }
      html += `</div>`;
    }
    html += `</div>`;
  }
  return html;
}

function renderDeviceTypeClustersDiff(diff) {
  let html = `<div class="detail-section"><div class="detail-section-title">Clusters</div>`;
  const added = diff.added || {};
  const removed = diff.removed || {};
  const modified = diff.modified || {};

  if (Object.keys(added).length) {
    html += `<table class="detail-table"><thead><tr><th>ID</th><th>Name</th><th>Side</th><th>Conformance</th><th>Status</th></tr></thead><tbody>`;
    for (const [key, item] of Object.entries(added)) {
      html += `<tr class="row-added">
        <td>${esc(item.id)}</td><td>${esc(item.name)}</td><td>${esc(item.side)}</td>
        <td>${esc(item.conformance)}</td><td><span class="badge-sm badge-added">ADDED</span></td></tr>`;
      if (item.features && Object.keys(item.features).length) {
        for (const [fc, fv] of Object.entries(item.features)) {
          html += `<tr class="row-added"><td colspan="5" style="padding-left:32px">Feature: <strong>${esc(fc)}</strong> (${esc(fv.conformance)})</td></tr>`;
        }
      }
      if (item.commands && Object.keys(item.commands).length) {
        for (const [ci, cv] of Object.entries(item.commands)) {
          html += `<tr class="row-added"><td colspan="5" style="padding-left:32px">Command: <strong>${esc(cv.name)}</strong> [${esc(ci)}] (${esc(cv.conformance)})</td></tr>`;
        }
      }
    }
    html += `</tbody></table>`;
  }

  if (Object.keys(removed).length) {
    html += `<table class="detail-table"><thead><tr><th>ID</th><th>Name</th><th>Side</th><th>Conformance</th><th>Status</th></tr></thead><tbody>`;
    for (const [key, item] of Object.entries(removed)) {
      html += `<tr class="row-removed">
        <td>${esc(item.id)}</td><td>${esc(item.name)}</td><td>${esc(item.side)}</td>
        <td>${esc(item.conformance)}</td><td><span class="badge-sm badge-removed">REMOVED</span></td></tr>`;
    }
    html += `</tbody></table>`;
  }

  if (Object.keys(modified).length) {
    for (const [key, mdata] of Object.entries(modified)) {
      const hasNewFormat = mdata && '_changes' in mdata;
      const changes = hasNewFormat ? mdata._changes : mdata;
      const newItem = hasNewFormat ? (mdata._new || {}) : {};
      const displayName = newItem.name ? `${esc(newItem.name)} [${esc(newItem.id || key)}] (${esc(newItem.side || '')})` : esc(key);

      html += `<div style="margin:6px 0;padding:8px;background:var(--modified-bg);border-radius:4px;border:1px solid var(--modified-border)">`;
      html += `<span class="badge-sm badge-modified">MODIFIED</span> <strong>${displayName}</strong>`;

      for (const [field, change] of Object.entries(changes || {})) {
        if (change && typeof change === 'object' && 'old' in change && 'new' in change) {
          html += `<div class="kv-change"><span class="kv-key">${esc(field)}:</span>
            <span class="val-old">${esc(formatVal(change.old))}</span>
            <span class="arrow">&rarr;</span>
            <span class="val-new">${esc(formatVal(change.new))}</span></div>`;
        } else if (change && typeof change === 'object' && ('added' in change || 'removed' in change || 'modified' in change)) {
          html += `<div style="margin-top:4px"><strong>${esc(field)}:</strong></div>`;
          if (change.added && Object.keys(change.added).length) {
            for (const [ak, av] of Object.entries(change.added)) {
              html += `<div style="padding:2px 0 2px 16px"><span class="badge-sm badge-added">+</span> `;
              if (typeof av === 'object') {
                html += Object.entries(av).map(([k2,v2]) => `<strong>${esc(k2)}</strong>=${esc(formatVal(v2))}`).join(' ');
              } else {
                html += `${esc(ak)}: ${esc(formatVal(av))}`;
              }
              html += `</div>`;
            }
          }
          if (change.removed && Object.keys(change.removed).length) {
            for (const [rk, rv] of Object.entries(change.removed)) {
              html += `<div style="padding:2px 0 2px 16px"><span class="badge-sm badge-removed">-</span> `;
              if (typeof rv === 'object') {
                html += Object.entries(rv).map(([k2,v2]) => `<strong>${esc(k2)}</strong>=${esc(formatVal(v2))}`).join(' ');
              } else {
                html += `${esc(rk)}: ${esc(formatVal(rv))}`;
              }
              html += `</div>`;
            }
          }
          if (change.modified && Object.keys(change.modified).length) {
            for (const [mk, mv] of Object.entries(change.modified)) {
              html += `<div style="padding:2px 0 2px 16px"><span class="badge-sm badge-modified">~</span> <strong>${esc(mk)}</strong>: `;
              if (mv && typeof mv === 'object') {
                for (const [f2, c2] of Object.entries(mv)) {
                  if (c2 && typeof c2 === 'object' && 'old' in c2) {
                    html += `${esc(f2)}: <span class="val-old">${esc(formatVal(c2.old))}</span><span class="arrow">&rarr;</span><span class="val-new">${esc(formatVal(c2.new))}</span> `;
                  }
                }
              }
              html += `</div>`;
            }
          }
        }
      }
      html += `</div>`;
    }
  }

  html += `</div>`;
  return html;
}

function renderConditionRequirementsDiff(diff) {
  let html = `<div class="detail-section"><div class="detail-section-title">Condition Requirements</div>`;
  const added = diff.added || {};
  const removed = diff.removed || {};
  const modified = diff.modified || {};

  for (const [key, item] of Object.entries(added)) {
    html += `<div style="margin:6px 0;padding:8px;background:var(--added-bg);border-radius:4px;border:1px solid var(--added-border)">`;
    html += `<span class="badge-sm badge-added">ADDED</span> <strong>${esc(item.name)}</strong> [${esc(item.id)}]`;
    if (item.requirements) {
      for (const [rk, rv] of Object.entries(item.requirements)) {
        html += `<div style="padding:2px 0 2px 16px">${esc(rv.name)}: <em>${esc(rv.conformance)}</em></div>`;
      }
    }
    html += `</div>`;
  }

  for (const [key, item] of Object.entries(removed)) {
    html += `<div style="margin:6px 0;padding:8px;background:var(--removed-bg);border-radius:4px;border:1px solid var(--removed-border)">`;
    html += `<span class="badge-sm badge-removed">REMOVED</span> <strong>${esc(item.name)}</strong> [${esc(item.id)}]`;
    if (item.requirements) {
      for (const [rk, rv] of Object.entries(item.requirements)) {
        html += `<div style="padding:2px 0 2px 16px">${esc(rv.name)}: <em>${esc(rv.conformance)}</em></div>`;
      }
    }
    html += `</div>`;
  }

  for (const [key, mdata] of Object.entries(modified)) {
    const hasNewFormat = mdata && '_changes' in mdata;
    const changes = hasNewFormat ? mdata._changes : mdata;
    const newItem = hasNewFormat ? (mdata._new || {}) : {};
    const displayName = newItem.name ? `${esc(newItem.name)} [${esc(newItem.id || '')}]` : esc(key);

    html += `<div style="margin:6px 0;padding:8px;background:var(--modified-bg);border-radius:4px;border:1px solid var(--modified-border)">`;
    html += `<span class="badge-sm badge-modified">MODIFIED</span> <strong>${displayName}</strong>`;
    for (const [field, change] of Object.entries(changes || {})) {
      if (field === 'requirements' && change && typeof change === 'object' && ('added' in change || 'removed' in change || 'modified' in change)) {
        if (change.added && Object.keys(change.added).length) {
          for (const [ak, av] of Object.entries(change.added)) {
            html += `<div style="padding:2px 0 2px 16px"><span class="badge-sm badge-added">+</span> ${esc(av.name)}: <em>${esc(av.conformance)}</em></div>`;
          }
        }
        if (change.removed && Object.keys(change.removed).length) {
          for (const [rk, rv] of Object.entries(change.removed)) {
            html += `<div style="padding:2px 0 2px 16px"><span class="badge-sm badge-removed">-</span> ${esc(rv.name)}: <em>${esc(rv.conformance)}</em></div>`;
          }
        }
        if (change.modified && Object.keys(change.modified).length) {
          for (const [mk, mv] of Object.entries(change.modified)) {
            html += `<div style="padding:2px 0 2px 16px"><span class="badge-sm badge-modified">~</span> ${esc(mk)}: `;
            if (mv && typeof mv === 'object' && 'old' in mv) {
              html += `<span class="val-old">${esc(formatVal(mv.old))}</span><span class="arrow">&rarr;</span><span class="val-new">${esc(formatVal(mv.new))}</span>`;
            } else if (mv && typeof mv === 'object') {
              for (const [f2, c2] of Object.entries(mv)) {
                if (c2 && typeof c2 === 'object' && 'old' in c2) {
                  html += `${esc(f2)}: <span class="val-old">${esc(formatVal(c2.old))}</span><span class="arrow">&rarr;</span><span class="val-new">${esc(formatVal(c2.new))}</span> `;
                }
              }
            }
            html += `</div>`;
          }
        }
      } else if (change && typeof change === 'object' && 'old' in change) {
        html += `<div class="kv-change"><span class="kv-key">${esc(field)}:</span>
          <span class="val-old">${esc(formatVal(change.old))}</span>
          <span class="arrow">&rarr;</span>
          <span class="val-new">${esc(formatVal(change.new))}</span></div>`;
      }
    }
    html += `</div>`;
  }

  html += `</div>`;
  return html;
}

function renderFullItem(data, isCluster, type) {
  let html = '';
  const cls = type === 'added' ? 'row-added' : 'row-removed';

  html += `<div class="kv-change"><span class="kv-key">ID:</span> ${esc(data.id)}</div>`;
  html += `<div class="kv-change"><span class="kv-key">Revision:</span> ${esc(data.revision)}</div>`;

  if (isCluster) {
    if (data.features && Object.keys(data.features).length) {
      html += `<div class="detail-section"><div class="detail-section-title">Features</div>`;
      html += `<table class="detail-table"><thead><tr><th>Bit</th><th>Code</th><th>Name</th><th>Summary</th><th>Conformance</th></tr></thead><tbody>`;
      for (const [k, f] of Object.entries(data.features)) {
        html += `<tr class="${cls}"><td>${esc(f.bit)}</td><td>${esc(f.code)}</td><td>${esc(f.name)}</td><td>${esc(f.summary)}</td><td>${esc(f.conformance)}</td></tr>`;
      }
      html += `</tbody></table></div>`;
    }

    if (data.attributes && Object.keys(data.attributes).length) {
      html += `<div class="detail-section"><div class="detail-section-title">Attributes</div>`;
      html += `<table class="detail-table"><thead><tr><th>ID</th><th>Name</th><th>Type</th><th>Conformance</th><th>Access</th></tr></thead><tbody>`;
      for (const [k, a] of Object.entries(data.attributes)) {
        html += `<tr class="${cls}"><td>${esc(a.id)}</td><td>${esc(a.name)}</td><td>${esc(a.type)}</td><td>${esc(a.conformance)}</td><td>${esc(a.access)}</td></tr>`;
      }
      html += `</tbody></table></div>`;
    }

    if (data.commands && Object.keys(data.commands).length) {
      html += `<div class="detail-section"><div class="detail-section-title">Commands</div>`;
      html += `<table class="detail-table"><thead><tr><th>ID</th><th>Name</th><th>Direction</th><th>Response</th><th>Conformance</th></tr></thead><tbody>`;
      for (const [k, c] of Object.entries(data.commands)) {
        html += `<tr class="${cls}"><td>${esc(c.id)}</td><td>${esc(c.name)}</td><td>${esc(c.direction)}</td><td>${esc(c.response)}</td><td>${esc(c.conformance)}</td></tr>`;
      }
      html += `</tbody></table></div>`;
    }

    if (data.events && Object.keys(data.events).length) {
      html += `<div class="detail-section"><div class="detail-section-title">Events</div>`;
      html += `<table class="detail-table"><thead><tr><th>ID</th><th>Name</th><th>Priority</th><th>Conformance</th></tr></thead><tbody>`;
      for (const [k, e] of Object.entries(data.events)) {
        html += `<tr class="${cls}"><td>${esc(e.id)}</td><td>${esc(e.name)}</td><td>${esc(e.priority)}</td><td>${esc(e.conformance)}</td></tr>`;
      }
      html += `</tbody></table></div>`;
    }
  } else {
    if (data.conditionRequirements && Object.keys(data.conditionRequirements).length) {
      html += `<div class="detail-section"><div class="detail-section-title">Condition Requirements</div>`;
      html += `<table class="detail-table"><thead><tr><th>Device Type</th><th>Condition</th><th>Conformance</th></tr></thead><tbody>`;
      for (const [k, cr] of Object.entries(data.conditionRequirements)) {
        for (const [rk, rv] of Object.entries(cr.requirements || {})) {
          html += `<tr class="${cls}"><td>${esc(cr.name)} [${esc(cr.id)}]</td><td>${esc(rv.name)}</td><td>${esc(rv.conformance)}</td></tr>`;
        }
      }
      html += `</tbody></table></div>`;
    }

    if (data.clusters && Object.keys(data.clusters).length) {
      html += `<div class="detail-section"><div class="detail-section-title">Required Clusters</div>`;
      html += `<table class="detail-table"><thead><tr><th>ID</th><th>Name</th><th>Side</th><th>Conformance</th></tr></thead><tbody>`;
      for (const [k, c] of Object.entries(data.clusters)) {
        html += `<tr class="${cls}"><td>${esc(c.id)}</td><td>${esc(c.name)}</td><td>${esc(c.side)}</td><td>${esc(c.conformance)}</td></tr>`;
      }
      html += `</tbody></table></div>`;
    }
  }

  return html;
}

function renderFieldChanges(changes) {
  let html = '';
  for (const c of changes) {
    html += `<div class="kv-change"><span class="kv-key">${esc(c.field)}:</span>
      <span class="val-old">${esc(String(c.old))}</span>
      <span class="arrow">&rarr;</span>
      <span class="val-new">${esc(String(c.new))}</span></div>`;
  }
  return html;
}

function toggleCard(id) {
  document.getElementById(id).classList.toggle('expanded');
}

function toggleAll(btn, catKey) {
  const container = document.getElementById('tab-' + catKey);
  if (!container) return;
  const cards = container.querySelectorAll('.diff-card');
  const anyCollapsed = Array.from(cards).some(c => !c.classList.contains('expanded'));
  cards.forEach(c => {
    if (anyCollapsed) c.classList.add('expanded');
    else c.classList.remove('expanded');
  });
  btn.textContent = anyCollapsed ? 'Collapse All' : 'Expand All';
}

function formatVal(v) {
  if (v === null || v === undefined) return '';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

function esc(s) {
  if (s == null) return '';
  const d = document.createElement('div');
  d.textContent = String(s);
  return d.innerHTML;
}

document.getElementById('nameFilter').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') runDiff();
});

// Theme toggle
(function() {
    const toggle = document.getElementById('themeToggle');
    const html = document.documentElement;

    function setTheme(theme) {
        html.setAttribute('data-theme', theme);
        localStorage.setItem('esp-matter-tools-theme', theme);
        toggle.innerHTML = theme === 'dark' ? '&#9788;' : '&#9790;';
        toggle.title = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
    }

    const saved = localStorage.getItem('esp-matter-tools-theme');
    setTheme(saved || 'light');

    toggle.addEventListener('click', function() {
        const current = html.getAttribute('data-theme');
        setTheme(current === 'dark' ? 'light' : 'dark');
    });
})();
