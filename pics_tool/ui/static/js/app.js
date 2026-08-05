// Copyright 2026 Espressif Systems (Shanghai) PTE LTD
// Licensed under the Apache License, Version 2.0. See LICENSE.

// ---- state ----
let pyodide = null;
let webapp = null;            // pics_tool.webapp module proxy
let payload = null;           // last generated payload
let tab = "base";             // active section tab (base | endpoint id)
let grp = "decided";          // active view: tool-decided items | manual selection
// answers/touched are keyed per (endpoint tab, code) -- the SAME PICS code can
// appear on several endpoints (Descriptor, On/Off), and each must be answerable
// independently. Key = `${tab}|${code}`.
let answers = {};             // "tab|code" -> "yes" | "no"
let touched = new Set();      // "tab|code" the human explicitly answered
let searchQ = "";             // current search text (survives tab re-render)
let deviceTypeNames = [];     // device-type names for the current spec version
let dirty = false;            // form edited since the last Generate (results stale)
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

// (endpoint tab, code) composite key helpers
const keyOf = (it) => `${it.tab}|${it.code}`;
function splitKey(k) { const i = k.indexOf("|"); return [k.slice(0, i), k.slice(i + 1)]; }

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

// ---- application endpoint rows (one device type per endpoint; "+" adds more) ----
function populateSelect(sel, chosen) {
  sel.innerHTML = "";
  // No device type is pre-selected: the user must choose one explicitly.
  const pick = deviceTypeNames.includes(chosen) ? chosen : "";
  sel.add(new Option("— Choose device type —", "", pick === "", pick === ""));
  deviceTypeNames.forEach((n) => sel.add(new Option(n, n, false, n === pick)));
  sel.value = pick;
}
function renumberEndpoints() {
  const rows = [...$("endpoints").querySelectorAll(".endpoint-row")];
  rows.forEach((r, i) => { r.querySelector(".ep-num").textContent = `${i + 1}`; });
  // the node must have at least one application endpoint
  rows.forEach((r) => { r.querySelector(".ep-remove").disabled = rows.length <= 1; });
}
function addEndpointRow(chosen) {
  const tpl = $("endpointRowTpl").content.firstElementChild.cloneNode(true);
  const sel = tpl.querySelector(".ep-devtype");
  populateSelect(sel, chosen);
  sel.addEventListener("change", markDirty);
  tpl.querySelector(".ep-remove").addEventListener("click", () => {
    tpl.remove(); renumberEndpoints(); markDirty();
  });
  $("endpoints").appendChild(tpl);
  renumberEndpoints();
}
function setEndpoints(deviceTypes) {
  $("endpoints").innerHTML = "";
  const list = (deviceTypes && deviceTypes.length) ? deviceTypes : [""];
  list.forEach((name) => addEndpointRow(name));
}
function endpointValues() {
  return [...$("endpoints").querySelectorAll(".ep-devtype")]
    .map((s) => ({ device_types: [s.value] }));
}

function readProfile() {
  // OTA is an either/or per Base.xml: no OTA Requestor => vendor-specific
  // OTA is mandatory for a commissionee (OTA Provider is profile/CLI-only in
  // phase 1).
  const ota = selected("ota")[0] || "vendor";
  return {
    spec_version: $("specVersion").value,
    endpoints: endpointValues(),        // [{device_types:[name]}] -> EP1..EPN
    node_device_types: ota === "requestor" ? ["OTA Requestor"] : [],
    vendor_specific_ota: ota === "vendor",
    transport: selected("transport"),
    ble_commissioning: selected("commdisc").includes("ble"),
    wifi_paf: selected("commdisc").includes("wifi_paf"),
    nfc_commissioning: selected("commdisc").includes("nfc"),
    onboarding: selected("onboarding"),
    role: selected("role")[0] || "commissionee",
    // IM role is always derived automatically (device type + claims)
  };
}

// device-type names for the version; (re)populate every endpoint row's select,
// preserving each row's current selection where the name still exists.
function loadDeviceTypes(version) {
  deviceTypeNames = JSON.parse(webapp.list_device_types_json(version));
  const rows = [...$("endpoints").querySelectorAll(".ep-devtype")];
  if (!rows.length) { setEndpoints([]); return; }
  rows.forEach((sel) => populateSelect(sel, sel.value));
}

// device types for the profile snapshot, new (endpoints) or old (device_type)
function profileDeviceTypes(p) {
  if (p.endpoints && p.endpoints.length)
    return p.endpoints.map((ep) => (ep.device_types || [])[0]).filter(Boolean);
  if (p.device_type) return [p.device_type];
  return [];
}

function applyProfileToForm(p) {
  if (!p) return;
  setEndpoints(profileDeviceTypes(p));
  setSelected("transport", p.transport || []);
  const disc = [];
  if (p.ble_commissioning !== false) disc.push("ble");
  if (p.wifi_paf) disc.push("wifi_paf");
  if (p.nfc_commissioning) disc.push("nfc");
  setSelected("commdisc", disc);
  setSelected("ota", [(p.node_device_types || []).includes("OTA Requestor")
    ? "requestor" : "vendor"]);
  // sessions saved during the brief 11/21 split map back to the single chip;
  // the manual-pairing-code chip is locked ON (every device ships one)
  const ob = (p.onboarding || []).map((o) =>
    o.startsWith("manual_pairing_code") ? "manual_pairing_code" : o);
  ob.push("manual_pairing_code");
  setSelected("onboarding", [...new Set(ob)]);
  setSelected("role", [p.role || "commissionee"]);
}

// A profile the engine would reject never reaches the engine: say what's wrong.
function validateProfile(p) {
  const errs = [];
  const dts = (p.endpoints || []).map((ep) => (ep.device_types || [])[0]).filter(Boolean);
  if (!dts.length) errs.push("Add at least one application endpoint with a device type.");
  if (!p.transport.length) errs.push("Pick at least one transport.");
  if (p.role === "commissionee" && !p.onboarding.length)
    errs.push("A commissionee needs at least one onboarding method (QR / manual pairing code / NFC).");
  if (p.wifi_paf && !p.transport.some((t) => t.startsWith("wifi")))
    errs.push("Wi-Fi PAF commissioning requires a Wi-Fi transport.");
  return errs;
}

// Inputs are NOT auto-generated: the user edits the profile, then clicks
// Generate. Every form change just re-checks validity (to enable/disable the
// Generate button) and, if results are already shown, flags them as stale.
function markDirty() {
  dirty = true;
  refreshValidity();
}
function refreshValidity() {
  const errs = validateProfile(readProfile());
  const btn = $("generateBtn");
  if (btn) {
    btn.disabled = errs.length > 0;
    btn.textContent = payload ? "Regenerate →" : "Generate PICS →";
  }
  const st = $("genStatus");
  if (st) {
    st.className = "gen-status";
    if (errs.length && dirty) { st.textContent = errs[0]; st.classList.add("warn"); }
    else if (payload && dirty) { st.textContent = "Inputs changed — click Regenerate to refresh."; st.classList.add("warn"); }
    else st.textContent = "";
  }
}

// Claims the user switched ON that carry spec consequences, grouped per endpoint
// tab so a feature/side claimed on EP1 never leaks to EP2. base -> MCORE atoms.
function claimsByTab(ans, tched) {
  const out = {};
  tched.forEach((k) => {
    const [t, code] = splitKey(k);
    if (ans[k] === "yes" &&
        (FEATURE_RE.test(code) || GATEWAY_RE.test(code) || code.startsWith("MCORE.")))
      (out[t] ??= []).push(code);
  });
  return out;
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
  loadDeviceTypes(vsel.value);
  vsel.addEventListener("change", () => { loadDeviceTypes(vsel.value); markDirty(); });

  if (session && session.profile) applyProfileToForm(session.profile);
  else setEndpoints([]);

  $("initOverlay").style.display = "none";
  refreshValidity();
  // Restore a prior session's results; a fresh visit waits for Generate.
  if (session && session.profile && validateProfile(readProfile()).length === 0) generate(session);
}

// ---- generate (runs automatically on every profile / claim change) ----
let genTimer = null;
function scheduleGenerate() {
  clearTimeout(genTimer);
  genTimer = setTimeout(() => generate(), 250);
}

function generate(session, announce) {
  const profile = readProfile();
  const errs = validateProfile(profile);
  if (errs.length) {
    payload = null;
    $("exportBtn").disabled = true;
    $("reviewActions").hidden = true;
    $("resultArea").innerHTML =
      `<div class="empty-state">${errs.map((e) => esc(e)).join("<br>")}</div>`;
    refreshValidity();
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
      runGenerate(profile, session ? session.answers : null,
                  session ? session.touched : null, announce);
    } catch (err) {
      $("resultArea").innerHTML = `<div class="empty-state">Generation failed: ${esc(err.message || err)}</div>`;
      console.error(err);
    } finally {
      $("resultArea").classList.remove("updating");
    }
  }, 30);
}

// Run the engine. User claims (features + cluster-side gateways), scoped per
// endpoint, re-enter it, so everything a claim makes mandatory flips to "yes"
// consistently on that endpoint only.
function runGenerate(profile, keepAnswers, keepTouched, announce) {
  const prevAnswers = keepAnswers || answers;
  const prevTouched = new Set(keepTouched || [...touched]);
  profile.claims_by_tab = claimsByTab(prevAnswers, prevTouched);

  payload = JSON.parse(webapp.generate_payload_json(JSON.stringify(profile), "[]"));

  // engine answers first, then the human's explicit overrides on top
  answers = {}; touched = new Set();
  payload.items.forEach((it) => { answers[keyOf(it)] = it.answer; });
  payload.items.forEach((it) => {
    const k = keyOf(it);
    if (prevTouched.has(k) && prevAnswers[k] !== undefined) {
      answers[k] = prevAnswers[k];
      touched.add(k);
    }
  });
  const y = window.scrollY;   // full re-render: keep the user's place
  render();
  window.scrollTo(0, y);
  $("exportBtn").disabled = false;
  $("reviewActions").hidden = false;   // review-step actions appear once generated
  dirty = false;
  saveSession();
  refreshValidity();
  if (announce) {   // explicit Generate click: confirm + move to the review step
    const st = $("genStatus");
    if (st) { st.textContent = "✓ Generated — review the answers below."; st.className = "gen-status ok"; }
    $("resultArea").scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

// ---- render ----
// The shell (tabs, stat bar, view switch, empty table) is built once per engine
// run; the row body holds ONLY the active tab's rows and is rebuilt on tab
// switch. This keeps the DOM to a single endpoint's rows instead of all of them.
function render() {
  const perTab = {};
  payload.items.forEach((it) => { perTab[it.tab] = (perTab[it.tab] || 0) + 1; });
  if (!payload.tabs.some((t) => t.id === tab)) tab = payload.tabs[0].id;
  const tabHtml = payload.tabs.map((t) =>
    `<button class="tab" data-tab="${esc(t.id)}" aria-pressed="${t.id === tab}">
       <span class="tt">${esc(t.label)}<span class="tn">${perTab[t.id] || 0}</span></span>
       <span class="tc">${esc(t.caption || "")}</span>
     </button>`).join("");

  $("resultArea").innerHTML = `
    <div class="reviewhead">
      <div class="card-title"><span class="stepno">2</span> Review the answers, then export</div>
      <div class="reviewtools">
        <label class="detailtoggle"><input type="checkbox" id="showDetails"> Show details</label>
        <div class="searchwrap">
          <input class="search" id="q" placeholder="Search questions or PICS codes"
            aria-label="Search questions or PICS codes">
        </div>
      </div>
    </div>
    <div class="statbar">
      <span class="stat on"><b id="t-yes">0</b> supported</span>
      <span class="stat off"><b id="t-no">0</b> not supported</span>
      <span class="stat mine"><b id="t-mine">0</b> changed by you</span>
    </div>
    <div class="tabs big">${tabHtml}</div>
    <div class="viewswitch" id="grpSwitch">
      <button class="chipf" data-g="decided" aria-pressed="${grp === "decided"}"><span class="sw" style="background:var(--on)"></span>Mandatory Items <span id="gc-decided"></span></button>
      <button class="chipf" data-g="manual" aria-pressed="${grp === "manual"}"><span class="sw" style="background:var(--review)"></span>Optional Items <span id="gc-manual"></span></button>
    </div>
    <div class="tablewrap attached"><table id="tbl">
      <thead><tr><th>Question</th><th class="answercol">Answer</th></tr></thead>
      <tbody id="tb"></tbody>
    </table></div>
    <div id="noMatchHint" class="hint" hidden></div>`;

  $("q").value = searchQ;
  wireShell();
  renderRows();
}

// Build the row body for the ACTIVE tab only (both groups; the view switch hides
// the inactive one). Questions are grouped under their cluster with a stable
// accent so long tables stay scannable.
function renderRows() {
  const clColor = {};
  let ci = 0;
  const colorOf = (cl) => (clColor[cl] ??= CLUSTER_PALETTE[ci++ % CLUSTER_PALETTE.length]);

  const rowsHtml = [];
  ["decided", "manual"].forEach((g) => {
    const members = payload.items
      .map((it, i) => ({ it, i }))
      .filter(({ it }) => it.tab === tab && it.group === g);
    const clusters = [];
    const byCl = new Map();
    members.forEach((m) => {
      if (!byCl.has(m.it.cluster)) { byCl.set(m.it.cluster, []); clusters.push(m.it.cluster); }
      byCl.get(m.it.cluster).push(m);
    });
    clusters.forEach((cl) => {
      const rows = byCl.get(cl);
      const key = `${tab}|${g}|${cl}`;
      const color = colorOf(cl);
      rowsHtml.push(`<tr class="clhdr" data-key="${esc(key)}">
        <td colspan="2"><span class="cldot" style="background:${color}"></span>${esc(cl)}
        <span class="clcount">${rows.length}</span></td></tr>`);
      rows.forEach(({ it, i }) => {
        const a = answers[keyOf(it)];
        // Server/Client side from the PICS code: the CSA templates reuse the
        // SAME question text for both sides (CNET.S.F01 vs CNET.C.F01), so
        // without this badge the two look like duplicates.
        const roleTok = it.code.startsWith("MCORE.") ? "" : it.code.split(".")[1];
        const side = roleTok === "S" ? "server" : roleTok === "C" ? "client" : "";
        const badge = side
          ? `<span class="sidebadge ${side}">${side === "server" ? "Server" : "Client"}</span>` : "";
        rowsHtml.push(`<tr data-i="${i}" data-tab="${esc(it.tab)}" data-group="${esc(it.group)}"
            data-key="${esc(key)}" style="--clc:${color}"
            class="${it.parent ? "childrow" : ""} ${isChanged(it) ? "changed" : ""}"
            data-code="${esc(it.code).toLowerCase()}" data-q="${esc((it.question || it.code)).toLowerCase()}">
          <td class="qcell">
            <div class="qtext">${esc(it.question || it.code)}${badge}</div>
            <div class="qmeta"><span class="code">${esc(it.code)}</span><span class="conf">${esc(it.conformance)}</span></div>
          </td>
          <td class="answercol">
            <div class="yn" data-k="${esc(keyOf(it))}" data-code="${esc(it.code)}">
              <button class="yn-btn yes ${a === "yes" ? "act" : ""}" data-a="yes" aria-label="Yes: ${esc(it.code)}">Yes</button>
              <button class="yn-btn no ${a === "no" ? "act" : ""}" data-a="no" aria-label="No: ${esc(it.code)}">No</button>
            </div>
          </td></tr>`);
      });
    });
  });
  $("tb").innerHTML = rowsHtml.join("");
  wireRows();
  applyFilter();
}

// wire the shell controls (tabs, search, view switch, details) -- once per render
function wireShell() {
  const RA = $("resultArea");
  RA.querySelectorAll(".tab").forEach((t) =>
    t.addEventListener("click", () => {
      tab = t.dataset.tab;
      RA.querySelectorAll(".tab").forEach((x) => x.setAttribute("aria-pressed", String(x === t)));
      renderRows();   // rebuild the body for the newly active endpoint
    }));
  let qTimer = null;
  $("q").addEventListener("input", (e) => {
    searchQ = e.target.value;
    clearTimeout(qTimer);
    qTimer = setTimeout(applyFilter, 150);   // debounce: don't scan on every keystroke
  });
  $("grpSwitch").querySelectorAll(".chipf").forEach((b) =>
    b.addEventListener("click", () => {
      grp = b.dataset.g;
      $("grpSwitch").querySelectorAll(".chipf").forEach((x) =>
        x.setAttribute("aria-pressed", String(x === b)));
      applyFilter();
    }));
  $("showDetails").addEventListener("change", (e) => $("tbl").classList.toggle("show-details", e.target.checked));
}

// wire the Yes/No toggles for the currently rendered rows
function wireRows() {
  $("tb").querySelectorAll(".yn").forEach((yn) => {
    const k = yn.dataset.k;             // "tab|code"
    const code = yn.dataset.code;       // bare code (for claim regex / child match)
    const btns = [...yn.querySelectorAll(".yn-btn")];
    btns.forEach((b) => b.addEventListener("click", () => {
      answers[k] = b.dataset.a;
      touched.add(k);
      btns.forEach((x) => x.classList.toggle("act", x === b));
      const tr = yn.closest("tr");
      tr.classList.toggle("changed", isChanged(payload.items[+tr.dataset.i]));
      // Un-claiming a parent (gateway X.C -> No, or a feature -> No) withdraws
      // everything revealed under it, ON THE SAME endpoint: drop manual
      // overrides on its children so nothing hidden leaks into the export.
      if (answers[k] === "no") {
        const [t] = splitKey(k);
        payload.items.forEach((it) => {
          if (it.tab === t && (it.parent === code
              || (GATEWAY_RE.test(code) && it.code.startsWith(code + ".")))) {
            const ck = keyOf(it);
            touched.delete(ck);
            answers[ck] = it.answer;
          }
        });
      }
      recount();
      saveSession();
      // claims (features, gateways, Base atoms) have spec consequences -> re-derive
      if (FEATURE_RE.test(code) || GATEWAY_RE.test(code) || code.startsWith("MCORE.")) scheduleGenerate();
      else applyFilter();
    }));
  });
  recount();
}

// Nested gateway model: an item with a parent (client sub-item under X.C,
// feature-dependent item under X.S.Fxx) is only shown while the parent is Yes.
// Anything currently answered Yes is always visible -- nothing enabled hides.
// Parent lookup is scoped to the item's own endpoint tab.
function isApplicable(it) {
  if (!it.parent) return true;
  if (answers[keyOf(it)] === "yes") return true;
  return answers[`${it.tab}|${it.parent}`] === "yes";
}

function applyFilter() {
  const q = searchQ.toLowerCase();
  // cross-scope search-hit counts computed from data (only the active tab's rows
  // are in the DOM, so "matches elsewhere" cannot come from a DOM scan).
  const scopeHits = {};   // "tab|group" -> hits
  const matches = (it) => isApplicable(it)
    && (!q || it.code.toLowerCase().includes(q) || (it.question || it.code).toLowerCase().includes(q));
  payload.items.forEach((it) => {
    if (matches(it)) scopeHits[`${it.tab}|${it.group}`] = (scopeHits[`${it.tab}|${it.group}`] || 0) + 1;
  });

  const clusterVisible = {};
  let visible = 0;
  $("tb").querySelectorAll("tr:not(.clhdr)").forEach((tr) => {
    const it = payload.items[+tr.dataset.i];
    const show = it.group === grp && matches(it);   // tab is implicit (only active rows rendered)
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
    const n = scopeHits[`${t.id}|${g}`];
    if (n) others.push({ t, g, n });
  }));
  hint.innerHTML = others.length
    ? "Nothing matches here — matches elsewhere: " + others.map(({ t, g, n }) =>
        `<button class="linklike" data-goto="${esc(t.id)}" data-g="${g}">${esc(t.label)} › ${g === "manual" ? "Optional Items" : "Mandatory Items"} (${n})</button>`).join(" · ")
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
  renderRows();
}

// "Changed by you" = differs from the PROFILE-ONLY baseline. Manual items
// baseline to No, so any manual Yes -- clicked directly or derived from your
// claim -- is yours, even after a regeneration bakes the claim into payload.
function isChanged(it) {
  return it.group === "manual" ? answers[keyOf(it)] === "yes"
                               : answers[keyOf(it)] !== it.answer;
}

// Whole-device counts (all endpoints): what the exported PICS will actually say.
function recount() {
  let yes = 0, no = 0, mine = 0;
  payload.items.forEach((it) => {
    if (answers[keyOf(it)] === "yes") yes++; else no++;
    if (isChanged(it)) mine++;
  });
  const set = (id, v) => { const e = $(id); if (e) e.textContent = v; };
  set("t-yes", yes); set("t-no", no); set("t-mine", mine);
}

// ---- export (with a spec-consistency gate) ----
// {tab: [codes]} — so every claim is exported into the SAME endpoint file the
// user answered it on (clusters like Descriptor exist on several endpoints).
function enabledByTab() {
  const out = {};
  payload.items.forEach((it) => {
    if (answers[keyOf(it)] === "yes") (out[it.tab] ??= []).push(it.code);
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
    const problems = JSON.parse(
      webapp.validate_selection_json(profileJson, JSON.stringify(enabledByTab())));
    const errors = problems.filter((p) => p.severity !== "warning");
    const warns = problems.filter((p) => p.severity === "warning");
    if (errors.length) {
      const fix = await confirmProblems(errors, warns);
      if (fix === null) return; // cancelled
      if (fix) {
        // enable each on the endpoint(s) the validator flagged it for
        errors.forEach((p) => {
          const t = p.tab || tab;
          answers[`${t}|${p.code}`] = "yes"; touched.add(`${t}|${p.code}`);
        });
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
    const label = (payload.device_type || "device").replace(/[^a-z0-9]+/gi, "_");
    a.download = `pics_${label}.zip`;
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
function confirmProblems(problems, warns = []) {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    const warnHtml = warns.length ? `
        <details class="expected"><summary>${warns.length} expected validator
          notice${warns.length > 1 ? "s" : ""} (no action needed)</summary>
          <ul>${warns.map((p) =>
            `<li><span class="code">${esc(p.code)}</span><br><small>${esc(p.why)}</small></li>`).join("")}</ul>
        </details>` : "";
    overlay.innerHTML = `
      <div class="modal" role="alertdialog" aria-label="Spec consistency check">
        <h3>The spec requires ${problems.length} more item${problems.length > 1 ? "s" : ""}</h3>
        <p>Given your answers, these are mandatory but currently "No":</p>
        <ul>${problems.slice(0, 12).map((p) =>
          `<li><span class="code">${esc(p.code)}</span> — ${esc(p.question)}<br><small>${esc(p.why)}</small></li>`).join("")}
        ${problems.length > 12 ? `<li>… and ${problems.length - 12} more</li>` : ""}</ul>
        ${warnHtml}
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

// ---- clear my answers (keep the profile; re-derive from the engine) ----
function resetAll() {
  answers = {}; touched = new Set();
  saveSession();
  if (payload) generate();      // re-derive the same profile, dropping manual edits
  else refreshValidity();
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
wireChips("commdisc", false);
wireChips("ota", true);
wireChips("role", true);
// results update automatically on any form change — no Generate button
["transport", "onboarding", "commdisc", "ota", "role"].forEach((id) =>
  $(id).addEventListener("click", (e) => { if (e.target.closest(".opt")) markDirty(); }));
$("addEndpoint").addEventListener("click", () => { addEndpointRow(); markDirty(); });
$("generateBtn").addEventListener("click", () => generate(null, true));
$("exportBtn").addEventListener("click", exportPICS);
$("resetBtn").addEventListener("click", resetAll);

init().catch((err) => {
  $("initStatus").textContent = "Failed to initialize: " + (err.message || err);
  console.error(err);
});
