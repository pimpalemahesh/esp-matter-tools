// Copyright 2025 Espressif Systems (Shanghai) PTE LTD
// Licensed under the Apache License, Version 2.0. See LICENSE.

// ---- state ----
let pyodide = null;
let webapp = null;            // pics_tool.webapp module proxy
let payload = null;           // last generated payload
let tab = "base";             // active section tab (base | endpoint id)
let grp = "decided";          // active view: tool-decided items | manual selection
let answers = {};             // code -> "yes" | "no" (the human's current answer)
let touched = new Set();      // codes the human explicitly answered
const BASE = new URL(".", window.location.href).href;
// distinct accent per cluster group (dot + row edge), stable per session
const CLUSTER_PALETTE = ["#2f6fed", "#0ea5a4", "#8b5cf6", "#d97706", "#16a34a",
  "#dc2626", "#0284c7", "#c026d3", "#65a30d", "#e0708c"];
const SESSION_KEY = "pics-workbench-session-v1";
const FEATURE_RE = /^[A-Z0-9_]+\.S\.F[0-9a-fA-F]{2}$/;
// gateway (cluster-side) items: claiming X.S / X.C reveals + derives its sub-items
const GATEWAY_RE = /^[A-Z0-9_]+\.[SC]$/;

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ---- chip helpers ----
function selected(groupId) {
  return [...$(groupId).querySelectorAll('.opt[aria-pressed="true"]')].map((b) => b.dataset.v);
}
function setSelected(groupId, values) {
  $(groupId).querySelectorAll(".opt").forEach((b) =>
    b.setAttribute("aria-pressed", String(values.includes(b.dataset.v))));
}
function wireChips(groupId, single) {
  $(groupId).addEventListener("click", (e) => {
    const btn = e.target.closest(".opt");
    if (!btn) return;
    if (single) {
      $(groupId).querySelectorAll(".opt").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
    } else {
      btn.setAttribute("aria-pressed", btn.getAttribute("aria-pressed") === "true" ? "false" : "true");
    }
  });
}

function readProfile() {
  const im = selected("imrole")[0] || "auto";
  return {
    spec_version: $("specVersion").value,
    device_type: $("deviceType").value,
    transport: selected("transport"),
    ble_commissioning: selected("ble")[0] === "on",
    onboarding: selected("onboarding"),
    role: selected("role")[0] || "commissionee",
    im_client: im === "auto" ? null : im === "client",
  };
}

function loadDeviceTypes(version, preferred) {
  const sel = $("deviceType");
  sel.innerHTML = "";
  const names = JSON.parse(webapp.list_device_types_json(version));
  const pick = names.includes(preferred) ? preferred : "Extended Color Light";
  names.forEach((n) => sel.add(new Option(n, n, false, n === pick)));
}

function applyProfileToForm(p) {
  if (!p) return;
  if (p.device_type) $("deviceType").value = p.device_type;
  setSelected("transport", p.transport || []);
  setSelected("ble", [p.ble_commissioning === false ? "off" : "on"]);
  setSelected("onboarding", p.onboarding || []);
  setSelected("role", [p.role || "commissionee"]);
  setSelected("imrole", [p.im_client === true ? "client"
    : p.im_client === false ? "server" : "auto"]);
}

// A profile the engine would reject never reaches the engine: say what's wrong.
function validateProfile(p) {
  const errs = [];
  if (!p.device_type) errs.push("Pick an application device type.");
  if (!p.transport.length) errs.push("Pick at least one transport.");
  if (p.role === "commissionee" && !p.onboarding.length)
    errs.push("A commissionee needs at least one onboarding method (QR / manual pairing code / NFC).");
  return errs;
}

// ---- session persistence (survives reload; cleared by Reset) ----
function saveSession() {
  try {
    localStorage.setItem(SESSION_KEY, JSON.stringify({
      profile: payload ? payload.profile : readProfile(),
      answers, touched: [...touched],
    }));
  } catch (e) { /* storage full/blocked: persistence is best-effort */ }
}
function loadSession() {
  try { return JSON.parse(localStorage.getItem(SESSION_KEY)); } catch (e) { return null; }
}
function clearSession() {
  localStorage.removeItem(SESSION_KEY);
  answers = {}; touched = new Set();
}

// ---- init ----
async function init() {
  const status = $("initStatus");
  status.textContent = "Loading Python runtime (Pyodide)...";
  pyodide = await loadPyodide();

  status.textContent = "Loading dependencies (PyYAML)...";
  await pyodide.loadPackage("pyyaml");

  status.textContent = "Loading PICS engine...";
  const buf = await (await fetch(BASE + "web_bundle/pics_bundle.zip")).arrayBuffer();
  try { pyodide.FS.mkdir("/bundle"); } catch (e) { /* exists */ }
  pyodide.unpackArchive(buf, "zip", { extractDir: "/bundle" });
  pyodide.runPython("import sys\nif '/bundle' not in sys.path: sys.path.insert(0, '/bundle')");
  webapp = pyodide.pyimport("pics_tool.webapp");

  // spec versions: whatever this build ships data for (newest preselected)
  const versions = JSON.parse(webapp.list_versions_json());
  const vsel = $("specVersion");
  versions.forEach((v) => vsel.add(new Option(`Matter ${v}`, v)));
  const session = loadSession();
  const savedV = session && session.profile && session.profile.spec_version;
  vsel.value = versions.includes(savedV) ? savedV : versions[versions.length - 1];
  loadDeviceTypes(vsel.value, session && session.profile && session.profile.device_type);
  vsel.addEventListener("change", () => { loadDeviceTypes(vsel.value); scheduleGenerate(); });

  if (session && session.profile) applyProfileToForm(session.profile);

  $("initOverlay").style.display = "none";
  generate(session); // show the default (or restored) device immediately
}

// ---- generate (runs automatically on every profile / claim change) ----
let genTimer = null;
function scheduleGenerate() {
  clearTimeout(genTimer);
  genTimer = setTimeout(() => generate(), 250);
}

function generate(session) {
  const profile = readProfile();
  const errs = validateProfile(profile);
  if (errs.length) {
    payload = null;
    $("exportBtn").disabled = true;
    $("resultArea").innerHTML =
      `<div class="empty-state">${errs.map((e) => esc(e)).join("<br>")}</div>`;
    return;
  }
  // first run: full spinner; later runs: dim the results while updating in place
  if (!payload) {
    $("resultArea").innerHTML = `<div class="loading"><div class="spinner"></div><div>Running the engine...</div></div>`;
  } else {
    $("resultArea").classList.add("updating");
  }
  // defer so the paint happens before the (synchronous) Python call
  setTimeout(() => {
    try {
      runGenerate(profile, session ? session.answers : null, session ? session.touched : null);
    } catch (err) {
      $("resultArea").innerHTML = `<div class="empty-state">Generation failed: ${esc(err.message || err)}</div>`;
      console.error(err);
    } finally {
      $("resultArea").classList.remove("updating");
    }
  }, 30);
}

// Run the engine. User claims (features + cluster-side gateways) re-enter it,
// so everything a claim makes mandatory flips to "yes" consistently.
function runGenerate(profile, keepAnswers, keepTouched) {
  const prevAnswers = keepAnswers || answers;
  const prevTouched = new Set(keepTouched || [...touched]);
  const claims = Object.keys(prevAnswers).filter((c) =>
    (FEATURE_RE.test(c) || GATEWAY_RE.test(c))
    && prevAnswers[c] === "yes" && prevTouched.has(c));

  payload = JSON.parse(webapp.generate_payload_json(
    JSON.stringify(profile), JSON.stringify(claims)));

  // engine answers first, then the human's explicit overrides on top
  answers = {}; touched = new Set();
  payload.items.forEach((it) => { answers[it.code] = it.answer; });
  payload.items.forEach((it) => {
    if (prevTouched.has(it.code) && prevAnswers[it.code] !== undefined) {
      answers[it.code] = prevAnswers[it.code];
      touched.add(it.code);
    }
  });
  const y = window.scrollY;   // full re-render: keep the user's place
  render();
  window.scrollTo(0, y);
  $("exportBtn").disabled = false;
  saveSession();
}

// ---- render ----
function render() {
  const perTab = {};
  payload.items.forEach((it) => { perTab[it.tab] = (perTab[it.tab] || 0) + 1; });
  if (!payload.tabs.some((t) => t.id === tab)) tab = payload.tabs[0].id;
  const tabHtml = payload.tabs.map((t) =>
    `<button class="tab" data-tab="${esc(t.id)}" aria-pressed="${t.id === tab}">${esc(t.label)}<span class="tn">${perTab[t.id] || 0}</span></button>`).join("");

  const derived = payload.im_client_derived ? "IM client + server" : "IM server only";
  $("imRole").innerHTML = payload.im_client_overridden
    ? `You overrode the derived value (<b>${esc(derived)}</b>) with <b>${esc(payload.im_role)}</b>.`
    : `Derived from the device type: <b>${esc(payload.im_role)}</b>.`;

  $("resultArea").innerHTML = `
    <div class="card-title"><span class="stepno">2</span> Review the answers, then export</div>
    <div class="tiles">
      <div class="tile on"><div class="big" id="t-yes">0</div><div class="lbl">supported (Yes)</div></div>
      <div class="tile off"><div class="big" id="t-no">0</div><div class="lbl">not supported (No)</div></div>
      <div class="tile mine"><div class="big" id="t-mine">0</div><div class="lbl">changed by you</div></div>
    </div>
    <div class="toolbar">
      <div class="tabs">${tabHtml}</div>
      <div class="filters" id="grpSwitch">
        <button class="chipf" data-g="decided" aria-pressed="${grp === "decided"}"><span class="sw" style="background:var(--on)"></span>Selected by the tool <span id="gc-decided"></span></button>
        <button class="chipf" data-g="manual" aria-pressed="${grp === "manual"}"><span class="sw" style="background:var(--review)"></span>Manual selection <span id="gc-manual"></span></button>
      </div>
      <label class="detailtoggle"><input type="checkbox" id="showDetails"> Technical details</label>
      <input class="search" id="q" placeholder="Search questions…" aria-label="Search questions">
    </div>
    <div class="tablewrap"><table id="tbl">
      <thead><tr><th>Question</th><th class="answercol">Answer</th></tr></thead>
      <tbody id="tb"></tbody>
    </table></div>
    <div id="noMatchHint" class="hint" hidden></div>`;

  // The two groups are exclusive views (switched above the table), never mixed:
  // "Selected by the tool" = defendable engine answers; "Manual selection" =
  // everything else in the same templates, default No, for the user to claim.
  // Within a view, questions are grouped under their cluster (or MCORE area),
  // each with a stable accent color, so long tables stay scannable.
  const clColor = {};
  let ci = 0;
  const colorOf = (cl) => (clColor[cl] ??= CLUSTER_PALETTE[ci++ % CLUSTER_PALETTE.length]);

  const rowsHtml = [];
  payload.tabs.forEach((t) => ["decided", "manual"].forEach((g) => {
    const members = payload.items
      .map((it, i) => ({ it, i }))
      .filter(({ it }) => it.tab === t.id && it.group === g);
    const clusters = [];
    const byCl = new Map();
    members.forEach((m) => {
      if (!byCl.has(m.it.cluster)) { byCl.set(m.it.cluster, []); clusters.push(m.it.cluster); }
      byCl.get(m.it.cluster).push(m);
    });
    clusters.forEach((cl) => {
      const rows = byCl.get(cl);
      const key = `${t.id}|${g}|${cl}`;
      const color = colorOf(cl);
      rowsHtml.push(`<tr class="clhdr" data-key="${esc(key)}">
        <td colspan="2"><span class="cldot" style="background:${color}"></span>${esc(cl)}
        <span class="clcount">${rows.length}</span></td></tr>`);
      rows.forEach(({ it, i }) => {
        const a = answers[it.code];
        // Server/Client side from the PICS code: the CSA templates reuse the
        // SAME question text for both sides (CNET.S.F01 vs CNET.C.F01), so
        // without this badge the two look like duplicates.
        const roleTok = it.code.startsWith("MCORE.") ? "" : it.code.split(".")[1];
        const side = roleTok === "S" ? "server" : roleTok === "C" ? "client" : "";
        const badge = side
          ? `<span class="sidebadge ${side}">${side === "server" ? "Server" : "Client"}</span>` : "";
        rowsHtml.push(`<tr data-i="${i}" data-tab="${esc(it.tab)}" data-group="${esc(it.group)}"
            data-key="${esc(key)}" style="--clc:${color}" class="${it.parent ? "childrow" : ""}"
            data-code="${esc(it.code).toLowerCase()}" data-q="${esc((it.question || it.code)).toLowerCase()}">
          <td class="qcell">
            <div class="qtext">${esc(it.question || it.code)}${badge}</div>
            <div class="qmeta"><span class="code">${esc(it.code)}</span><span class="conf">${esc(it.conformance)}</span></div>
          </td>
          <td class="answercol">
            <div class="yn" data-code="${esc(it.code)}">
              <button class="yn-btn yes ${a === "yes" ? "act" : ""}" data-a="yes" aria-label="Yes: ${esc(it.code)}">Yes</button>
              <button class="yn-btn no ${a === "no" ? "act" : ""}" data-a="no" aria-label="No: ${esc(it.code)}">No</button>
            </div>
          </td></tr>`);
      });
    });
  }));
  $("tb").innerHTML = rowsHtml.join("");

  wireResults();
  applyFilter();
}

function wireResults() {
  const RA = $("resultArea");
  RA.querySelectorAll(".tab").forEach((t) =>
    t.addEventListener("click", () => {
      tab = t.dataset.tab;
      RA.querySelectorAll(".tab").forEach((x) => x.setAttribute("aria-pressed", String(x === t)));
      applyFilter();
    }));
  $("q").addEventListener("input", applyFilter);
  $("grpSwitch").querySelectorAll(".chipf").forEach((b) =>
    b.addEventListener("click", () => {
      grp = b.dataset.g;
      $("grpSwitch").querySelectorAll(".chipf").forEach((x) =>
        x.setAttribute("aria-pressed", String(x === b)));
      applyFilter();
    }));
  $("showDetails").addEventListener("change", (e) => $("tbl").classList.toggle("show-details", e.target.checked));

  $("tb").querySelectorAll(".yn").forEach((yn) => {
    const code = yn.dataset.code;
    const btns = [...yn.querySelectorAll(".yn-btn")];
    btns.forEach((b) => b.addEventListener("click", () => {
      answers[code] = b.dataset.a;
      touched.add(code);
      btns.forEach((x) => x.classList.toggle("act", x === b));
      const tr = yn.closest("tr");
      tr.classList.toggle("changed", answers[code] !== payload.items[+tr.dataset.i].answer);
      // Un-claiming a parent (gateway X.C -> No, or a feature -> No) withdraws
      // everything revealed under it: drop manual overrides on its children so
      // nothing hidden leaks into the export.
      if (answers[code] === "no") {
        payload.items.forEach((it) => {
          if (it.parent === code
              || (GATEWAY_RE.test(code) && it.code.startsWith(code + "."))) {
            touched.delete(it.code);
            answers[it.code] = it.answer;
          }
        });
      }
      recount();
      saveSession();
      // claims (features, gateways) have spec consequences -> re-derive
      if (FEATURE_RE.test(code) || GATEWAY_RE.test(code)) scheduleGenerate();
      else applyFilter();
    }));
  });
  recount();
}

// Nested gateway model: an item with a parent (client sub-item under X.C,
// feature-dependent item under X.S.Fxx) is only shown while the parent is Yes.
// Anything currently answered Yes is always visible -- nothing enabled hides.
function isApplicable(it) {
  if (!it.parent) return true;
  if (answers[it.code] === "yes") return true;
  return answers[it.parent] === "yes";
}

function applyFilter() {
  const q = ($("q") ? $("q").value.toLowerCase() : "");
  const matchesElsewhere = {};   // "tabId|group" -> count of search hits
  const clusterVisible = {};     // "tabId|group|cluster" -> visible row count
  let visible = 0;
  $("tb").querySelectorAll("tr:not(.clhdr)").forEach((tr) => {
    const it = payload.items[+tr.dataset.i];
    const hit = isApplicable(it)
      && (!q || tr.dataset.code.includes(q) || tr.dataset.q.includes(q));
    if (hit) {
      const key = `${tr.dataset.tab}|${tr.dataset.group}`;
      matchesElsewhere[key] = (matchesElsewhere[key] || 0) + 1;
    }
    const show = tr.dataset.tab === tab && tr.dataset.group === grp && hit;
    if (show) { visible++; clusterVisible[tr.dataset.key] = (clusterVisible[tr.dataset.key] || 0) + 1; }
    tr.style.display = show ? "" : "none";
  });
  $("tb").querySelectorAll("tr.clhdr").forEach((tr) => {
    const n = clusterVisible[tr.dataset.key] || 0;
    tr.style.display = n ? "" : "none";
    const cnt = tr.querySelector(".clcount");
    if (cnt) cnt.textContent = n;
  });

  // per-tab counts on the two view buttons
  const counts = { decided: 0, manual: 0 };
  payload.items.forEach((it) => { if (it.tab === tab) counts[it.group]++; });
  const gset = (id, v) => { const e = $(id); if (e) e.textContent = `(${v})`; };
  gset("gc-decided", counts.decided); gset("gc-manual", counts.manual);

  // the table shows one tab+view; when search matches live elsewhere, link there
  const hint = $("noMatchHint");
  if (visible > 0 || !q) { hint.hidden = true; return; }
  const others = [];
  payload.tabs.forEach((t) => ["decided", "manual"].forEach((g) => {
    if (t.id === tab && g === grp) return;
    const n = matchesElsewhere[`${t.id}|${g}`];
    if (n) others.push({ t, g, n });
  }));
  hint.innerHTML = others.length
    ? "Nothing matches here — matches elsewhere: " + others.map(({ t, g, n }) =>
        `<button class="linklike" data-goto="${esc(t.id)}" data-g="${g}">${esc(t.label)} › ${g === "manual" ? "Manual selection" : "Selected by the tool"} (${n})</button>`).join(" · ")
    : "Nothing matches.";
  hint.hidden = false;
  hint.querySelectorAll("[data-goto]").forEach((b) =>
    b.addEventListener("click", () => switchTo(b.dataset.goto, b.dataset.g)));
}

function switchTo(tabId, group) {
  tab = tabId;
  grp = group;
  $("resultArea").querySelectorAll(".tab").forEach((x) =>
    x.setAttribute("aria-pressed", String(x.dataset.tab === tabId)));
  $("grpSwitch").querySelectorAll(".chipf").forEach((x) =>
    x.setAttribute("aria-pressed", String(x.dataset.g === group)));
  applyFilter();
}

// Whole-device counts (all endpoints): what the exported PICS will actually say.
function recount() {
  let yes = 0, no = 0, mine = 0;
  payload.items.forEach((it) => {
    if (answers[it.code] === "yes") yes++; else no++;
    if (answers[it.code] !== it.answer) mine++;
  });
  const set = (id, v) => { const e = $(id); if (e) e.textContent = v; };
  set("t-yes", yes); set("t-no", no); set("t-mine", mine);
}

// ---- export (with a spec-consistency gate) ----
function enabledCodes() {
  return payload.items.map((it) => it.code).filter((c) => answers[c] === "yes");
}
// {tab: [codes]} — so every claim is exported into the SAME endpoint file the
// user answered it on (clusters like Descriptor exist on several endpoints).
function enabledByTab() {
  const out = {};
  payload.items.forEach((it) => {
    if (answers[it.code] === "yes") (out[it.tab] ??= []).push(it.code);
  });
  return out;
}

async function exportPICS() {
  const btn = $("exportBtn");
  btn.disabled = true; btn.textContent = "Checking…";
  try {
    // Always export the profile snapshot that produced the visible payload —
    // never the current form, which the user may have changed since generating.
    const profileJson = JSON.stringify(payload.profile);
    const enabled = enabledCodes();
    const problems = JSON.parse(
      webapp.validate_selection_json(profileJson, JSON.stringify(enabled)));
    if (problems.length) {
      const fix = await confirmProblems(problems);
      if (fix === null) return; // cancelled
      if (fix) {
        problems.forEach((p) => { answers[p.code] = "yes"; touched.add(p.code); });
        render();
        saveSession();
      }
    }
    btn.textContent = "Building…";
    const files = JSON.parse(
      webapp.export_pics_files_json(profileJson, JSON.stringify(enabledByTab())));
    const zip = new JSZip();
    Object.entries(files).forEach(([path, text]) => zip.file(path, text));
    const blob = await zip.generateAsync({ type: "blob" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `pics_${payload.device_type.replace(/[^a-z0-9]+/gi, "_")}.zip`;
    a.click();
    URL.revokeObjectURL(a.href);
  } catch (err) {
    alert("Export failed: " + (err.message || err));
    console.error(err);
  } finally {
    btn.disabled = false; btn.textContent = "Export PICS ↓";
  }
}

// Modal listing spec-consistency problems. Resolves true = enable & continue,
// false = export as-is, null = cancel.
function confirmProblems(problems) {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.innerHTML = `
      <div class="modal" role="alertdialog" aria-label="Spec consistency check">
        <h3>The spec requires ${problems.length} more item${problems.length > 1 ? "s" : ""}</h3>
        <p>Given your answers, these are mandatory but currently "No":</p>
        <ul>${problems.slice(0, 12).map((p) =>
          `<li><span class="code">${esc(p.code)}</span> — ${esc(p.question)}<br><small>${esc(p.why)}</small></li>`).join("")}
        ${problems.length > 12 ? `<li>… and ${problems.length - 12} more</li>` : ""}</ul>
        <div class="modal-actions">
          <button class="btn" data-act="fix">Enable them &amp; export</button>
          <button class="btn ghost" data-act="asis">Export as-is</button>
          <button class="btn ghost" data-act="cancel">Cancel</button>
        </div>
      </div>`;
    overlay.addEventListener("click", (e) => {
      const act = e.target.dataset && e.target.dataset.act;
      if (!act && e.target !== overlay) return;
      overlay.remove();
      resolve(act === "fix" ? true : act === "asis" ? false : null);
    });
    document.body.appendChild(overlay);
  });
}

// ---- reset ----
function resetAll() {
  clearSession();
  tab = "base"; grp = "decided";
  generate();
}

// ---- theme toggle ----
(function () {
  const toggle = $("themeToggle");
  const html = document.documentElement;
  const cur = html.getAttribute("data-theme") || "light";
  toggle.textContent = cur === "dark" ? "☀️" : "🌙";
  toggle.addEventListener("click", () => {
    const next = html.getAttribute("data-theme") === "dark" ? "light" : "dark";
    html.setAttribute("data-theme", next);
    localStorage.setItem("esp-matter-tools-theme", next);
    toggle.textContent = next === "dark" ? "☀️" : "🌙";
  });
})();

// ---- wire form + boot ----
wireChips("transport", false);
wireChips("onboarding", false);
wireChips("ble", true);
wireChips("role", true);
wireChips("imrole", true);
// results update automatically on any form change — no Generate button
["transport", "onboarding", "ble", "role", "imrole"].forEach((id) =>
  $(id).addEventListener("click", (e) => { if (e.target.closest(".opt")) scheduleGenerate(); }));
$("deviceType").addEventListener("change", scheduleGenerate);
$("exportBtn").addEventListener("click", exportPICS);
$("resetBtn").addEventListener("click", resetAll);

init().catch((err) => {
  $("initStatus").textContent = "Failed to initialize: " + (err.message || err);
  console.error(err);
});
