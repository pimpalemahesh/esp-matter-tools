// Copyright 2025 Espressif Systems (Shanghai) PTE LTD
// Licensed under the Apache License, Version 2.0. See LICENSE.

// ---- state ----
let pyodide = null;
let webapp = null;            // pics_tool.webapp module proxy
let payload = null;           // last generated payload
let tab = "base";             // active section tab (base | endpoint id)
let answers = {};             // code -> "yes" | "no" (the human's current answer)
let touched = new Set();      // codes the human explicitly answered
const BASE = new URL(".", window.location.href).href;
const SPEC = "1.6";
const SESSION_KEY = "pics-workbench-session-v1";
const FEATURE_RE = /^[A-Z0-9_]+\.S\.F[0-9a-fA-F]{2}$/;

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
  const icd = selected("icd")[0] || "none";
  return {
    spec_version: SPEC,
    device_type: $("deviceType").value,
    node_device_types: selected("nodeTypes"),
    transport: selected("transport"),
    ble_commissioning: selected("ble")[0] === "on",
    onboarding: selected("onboarding"),
    role: selected("role")[0] || "commissionee",
    is_icd: icd !== "none",
    icd_mode: icd === "none" ? null : icd,
  };
}

function applyProfileToForm(p) {
  if (!p) return;
  if (p.device_type) $("deviceType").value = p.device_type;
  setSelected("nodeTypes", p.node_device_types || []);
  setSelected("transport", p.transport || []);
  setSelected("ble", [p.ble_commissioning === false ? "off" : "on"]);
  setSelected("onboarding", p.onboarding || []);
  setSelected("role", [p.role || "commissionee"]);
  setSelected("icd", [p.is_icd ? (p.icd_mode || "sit") : "none"]);
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

  // populate the device-type picker
  const names = JSON.parse(webapp.list_device_types_json(SPEC));
  const sel = $("deviceType");
  names.forEach((n) => sel.add(new Option(n, n, false, n === "Extended Color Light")));

  const session = loadSession();
  if (session && session.profile) applyProfileToForm(session.profile);

  $("generateBtn").disabled = false;
  $("initOverlay").style.display = "none";
  generate(session); // show the default (or restored) device immediately
}

// ---- generate ----
function generate(session) {
  const profile = readProfile();
  const errs = validateProfile(profile);
  if (errs.length) {
    $("resultArea").innerHTML =
      `<div class="empty-state">${errs.map((e) => esc(e)).join("<br>")}</div>`;
    return;
  }
  const btn = $("generateBtn");
  btn.disabled = true; btn.textContent = "Generating...";
  $("resultArea").innerHTML = `<div class="loading"><div class="spinner"></div><div>Running the engine...</div></div>`;
  // defer so the spinner paints before the (synchronous) Python call
  setTimeout(() => {
    try {
      runGenerate(profile, session ? session.answers : null, session ? session.touched : null);
    } catch (err) {
      $("resultArea").innerHTML = `<div class="empty-state">Generation failed: ${esc(err.message || err)}</div>`;
      console.error(err);
    } finally {
      btn.disabled = false; btn.textContent = "Generate PICS";
    }
  }, 30);
}

// Run the engine; user-enabled feature codes re-enter it as seeds so everything
// they make mandatory flips to "yes" consistently (not a raw row flip).
function runGenerate(profile, keepAnswers, keepTouched) {
  const prevAnswers = keepAnswers || answers;
  const prevTouched = new Set(keepTouched || [...touched]);
  const enabledFeatures = Object.keys(prevAnswers)
    .filter((c) => FEATURE_RE.test(c) && prevAnswers[c] === "yes" && prevTouched.has(c));

  payload = JSON.parse(webapp.generate_payload_json(
    JSON.stringify(profile), JSON.stringify(enabledFeatures)));

  // engine answers first, then the human's explicit overrides on top
  answers = {}; touched = new Set();
  payload.items.forEach((it) => { answers[it.code] = it.answer; });
  payload.items.forEach((it) => {
    if (prevTouched.has(it.code) && prevAnswers[it.code] !== undefined) {
      answers[it.code] = prevAnswers[it.code];
      touched.add(it.code);
    }
  });
  render();
  $("exportBtn").disabled = false;
  saveSession();
}

// ---- render ----
// Only engine-decided questions are shown; the undecided (review) items are
// kept out of the table but still travel in the payload and export as "No".
function isShown(it) { return !it.needs_you || touched.has(it.code); }

function render() {
  const perTab = {};
  payload.items.forEach((it) => {
    if (isShown(it)) perTab[it.tab] = (perTab[it.tab] || 0) + 1;
  });
  if (!payload.tabs.some((t) => t.id === tab)) tab = payload.tabs[0].id;
  const tabHtml = payload.tabs.map((t) =>
    `<button class="tab" data-tab="${esc(t.id)}" aria-pressed="${t.id === tab}">${esc(t.label)}<span class="tn">${perTab[t.id] || 0}</span></button>`).join("");

  $("imRole").innerHTML = `Role, derived from the device type: <b>${esc(payload.im_role)}</b>`;

  $("resultArea").innerHTML = `
    <div class="tiles">
      <div class="tile on"><div class="big" id="t-yes">0</div><div class="lbl">supported (Yes)</div></div>
      <div class="tile off"><div class="big" id="t-no">0</div><div class="lbl">not supported (No)</div></div>
    </div>
    <div id="recalcBanner" class="banner" hidden>
      You switched a feature on — recalculate so everything that feature makes
      mandatory is filled in for you.
      <button class="btn small" id="recalcBtn">Recalculate</button>
    </div>
    <div class="toolbar">
      <div class="tabs">${tabHtml}</div>
      <label class="detailtoggle"><input type="checkbox" id="showDetails"> Technical details</label>
      <input class="search" id="q" placeholder="Search questions…" aria-label="Search questions">
    </div>
    <div class="tablewrap"><table id="tbl">
      <thead><tr><th>Question</th><th class="answercol">Answer</th></tr></thead>
      <tbody id="tb"></tbody>
    </table></div>
    <div id="noMatchHint" class="hint" hidden></div>`;

  $("tb").innerHTML = payload.items.map((it, i) => {
    if (!isShown(it)) return "";
    const a = answers[it.code];
    return `<tr data-i="${i}" data-tab="${esc(it.tab)}" data-code="${esc(it.code).toLowerCase()}"
        data-q="${esc((it.question || it.code)).toLowerCase()}">
      <td class="qcell">
        <div class="qtext">${esc(it.question || it.code)}</div>
        <div class="qmeta"><span class="code">${esc(it.code)}</span><span class="conf">${esc(it.conformance)}</span></div>
      </td>
      <td class="answercol">
        <div class="yn" data-code="${esc(it.code)}">
          <button class="yn-btn yes ${a === "yes" ? "act" : ""}" data-a="yes" aria-label="Yes: ${esc(it.code)}">Yes</button>
          <button class="yn-btn no ${a === "no" ? "act" : ""}" data-a="no" aria-label="No: ${esc(it.code)}">No</button>
        </div>
      </td></tr>`;
  }).join("");

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
  $("showDetails").addEventListener("change", (e) => $("tbl").classList.toggle("show-details", e.target.checked));
  $("recalcBtn").addEventListener("click", () => runGenerate(payload.profile));

  $("tb").querySelectorAll(".yn").forEach((yn) => {
    const code = yn.dataset.code;
    const btns = [...yn.querySelectorAll(".yn-btn")];
    btns.forEach((b) => b.addEventListener("click", () => {
      answers[code] = b.dataset.a;
      touched.add(code);
      btns.forEach((x) => x.classList.toggle("act", x === b));
      const tr = yn.closest("tr");
      tr.classList.toggle("changed", answers[code] !== payload.items[+tr.dataset.i].answer);
      if (FEATURE_RE.test(code)) $("recalcBanner").hidden = false;
      recount();
      saveSession();
    }));
  });
  recount();
}

function applyFilter() {
  const q = ($("q") ? $("q").value.toLowerCase() : "");
  const matchesByTab = {};
  let visible = 0;
  $("tb").querySelectorAll("tr").forEach((tr) => {
    const hit = !q || tr.dataset.code.includes(q) || tr.dataset.q.includes(q);
    if (hit) matchesByTab[tr.dataset.tab] = (matchesByTab[tr.dataset.tab] || 0) + 1;
    const show = tr.dataset.tab === tab && hit;
    if (show) visible++;
    tr.style.display = show ? "" : "none";
  });
  // The search only shows the current tab; when the matches live on another
  // tab, say so instead of presenting a silently empty table.
  const hint = $("noMatchHint");
  if (visible > 0 || !q) { hint.hidden = true; return; }
  const others = payload.tabs.filter((t) => t.id !== tab && matchesByTab[t.id]);
  hint.innerHTML = others.length
    ? "Nothing matches on this tab — matches elsewhere: " + others.map((t) =>
        `<button class="linklike" data-goto="${esc(t.id)}">${esc(t.label)} (${matchesByTab[t.id]})</button>`).join(" · ")
    : "Nothing matches.";
  hint.hidden = false;
  hint.querySelectorAll("[data-goto]").forEach((b) =>
    b.addEventListener("click", () => switchTab(b.dataset.goto)));
}

function switchTab(id) {
  tab = id;
  $("resultArea").querySelectorAll(".tab").forEach((x) =>
    x.setAttribute("aria-pressed", String(x.dataset.tab === id)));
  applyFilter();
}

// Whole-device counts (all endpoints): what the exported PICS will actually say.
function recount() {
  let yes = 0, no = 0;
  payload.items.forEach((it) => {
    if (answers[it.code] === "yes") yes++; else no++;
  });
  const set = (id, v) => { const e = $(id); if (e) e.textContent = v; };
  set("t-yes", yes); set("t-no", no);
}

// ---- export (with a spec-consistency gate) ----
function enabledCodes() {
  return payload.items.map((it) => it.code).filter((c) => answers[c] === "yes");
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
      webapp.export_pics_files_json(profileJson, JSON.stringify(enabledCodes())));
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
  tab = "base";
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
wireChips("nodeTypes", false);
wireChips("transport", false);
wireChips("onboarding", false);
wireChips("ble", true);
wireChips("role", true);
wireChips("icd", true);
$("generateBtn").addEventListener("click", () => generate());
$("exportBtn").addEventListener("click", exportPICS);
$("resetBtn").addEventListener("click", resetAll);

init().catch((err) => {
  $("initStatus").textContent = "Failed to initialize: " + (err.message || err);
  console.error(err);
});
