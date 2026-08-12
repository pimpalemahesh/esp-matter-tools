// Copyright 2026 Espressif Systems (Shanghai) PTE LTD
// Licensed under the Apache License, Version 2.0. See LICENSE.

// ---- state ----
let pyodide = null;
let webapp = null;            // pics_tool.webapp module proxy
let payload = null;           // last generated payload
let tab = "base";             // active section tab (base | endpoint id)
let grp = "decided";          // active view: tool-decided items | manual selection
// Review presentation mode. "simple" (default): only the optional choices, as
// one-click chips grouped by cluster -- everything the tool decided collapses
// into a single banner. "advanced": every question (Mandatory + Optional) as
// full Yes/No rows, exactly the complete PICS item list.
const MODE_KEY = "pics-view-mode-v1";
let mode = localStorage.getItem(MODE_KEY) === "advanced" ? "advanced" : "simple";
// answers/touched are keyed per (endpoint tab, code) -- the SAME PICS code can
// appear on several endpoints (Descriptor, On/Off), and each must be answerable
// independently. Key = `${tab}|${code}`.
let answers = {};             // "tab|code" -> "yes" | "no"
let touched = new Set();      // "tab|code" the human explicitly answered
let searchQ = "";             // current search text (survives tab re-render)
let revShowAll = false;       // export review: my selections (default) | all optional questions
let deviceTypeNames = [];     // device-type names for the current spec version
let dirty = false;            // form edited since the last Generate (results stale)
let collapsed = new Set();    // cluster keys ("tab|group|cluster") folded shut in the review
let scaffoldSnippet = "";     // last-generated esp-matter data-model code (for copy/download)
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
  // Secondary Network Interface is infrastructure the transport section
  // manages automatically -- never offered as an application device type.
  const pick = deviceTypeNames.includes(chosen) ? chosen : "";
  sel.add(new Option("— Choose device type —", "", pick === "", pick === ""));
  deviceTypeNames.forEach((n) => {
    if (n !== SNI_NAME) sel.add(new Option(n, n, false, n === pick));
  });
  sel.value = pick;
}
// ---- multi-interface nodes (Secondary Network Interface, spec 11.9) ----
// A node with several network technologies hosts one Network Commissioning
// instance per interface, each on its own endpoint. The user only picks the
// PRIMARY (it lives on endpoint 0); the tool appends a Secondary Network
// Interface endpoint automatically for every other technology (readProfile),
// so the endpoint plumbing never surfaces in the form.
const SNI_NAME = "Secondary Network Interface";
const IFACE_LABELS = { wifi: "Wi-Fi", thread: "Thread", ethernet: "Ethernet" };
function transportFamilies() {
  return [...new Set(selected("transport").map((t) => (t.startsWith("wifi") ? "wifi" : t)))];
}
function refreshPrimary(keep) {
  const fams = transportFamilies();
  const cur0 = keep || selected("primary")[0];
  const cur = fams.includes(cur0) ? cur0 : fams[0];
  $("primaryWrap").hidden = fams.length <= 1;
  const group = $("primary");
  group.innerHTML = "";
  fams.forEach((f) => {
    const b = document.createElement("button");
    b.className = "opt seg-one";
    b.dataset.v = f;
    b.textContent = IFACE_LABELS[f] || f;
    b.setAttribute("aria-pressed", String(f === cur));
    group.appendChild(b);
  });
  updatePrimaryHint();
}
function updatePrimaryHint() {
  const fams = transportFamilies();
  const el = $("primaryHint");
  if (fams.length <= 1) { el.textContent = ""; return; }
  const prim = selected("primary")[0] || fams[0];
  const others = fams.filter((f) => f !== prim).map((f) => IFACE_LABELS[f] || f);
  el.textContent = `${IFACE_LABELS[prim] || prim} runs on the Root Node (endpoint 0); `
    + `${others.join(", ")} get${others.length > 1 ? "" : "s"} an automatic `
    + `Secondary Network Interface endpoint.`;
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
function setEndpoints(endpoints) {
  // accepts [{device_types}] (profile entries) or plain name strings
  $("endpoints").innerHTML = "";
  const list = (endpoints && endpoints.length) ? endpoints : [""];
  list.forEach((e) => addEndpointRow(
    typeof e === "string" ? e : (e.device_types || [])[0] || ""));
}
function endpointValues() {
  return [...$("endpoints").querySelectorAll(".ep-devtype")]
    .map((s) => ({ device_types: [s.value] }));
}

function readProfile() {
  // OTA is an either/or per Base.xml: Matter OTA (OTA Requestor) is the default;
  // vendor-specific is the alternative. OTA is mandatory for a commissionee
  // (OTA Provider is profile/CLI-only in phase 1).
  const ota = selected("ota")[0] || "requestor";
  // Multi-interface node: an automatic Secondary Network Interface endpoint
  // per non-primary technology (one Network Commissioning instance per
  // interface, spec 11.9). The primary stays on the Root Node (EP0).
  const eps = endpointValues();
  const fams = transportFamilies();
  if (fams.length > 1) {
    const prim = selected("primary")[0] || fams[0];
    fams.filter((f) => f !== prim).forEach((f) =>
      eps.push({ device_types: [SNI_NAME], interface: f }));
  }
  return {
    spec_version: $("specVersion").value,
    endpoints: eps,                     // [{device_types:[name]}] -> EP1..EPN
    node_device_types: ota === "requestor" ? ["OTA Requestor"] : [],
    vendor_specific_ota: ota === "vendor",
    transport: selected("transport"),
    ble_commissioning: selected("commdisc").includes("ble"),
    wifi_paf: selected("commdisc").includes("wifi_paf"),
    nfc_commissioning: selected("commdisc").includes("nfc"),
    onboarding: selected("onboarding"),
    commissioning_flow: selected("flow")[0] || "standard",
    tcp: selected("netcaps").includes("tcp"),
    extended_discovery: selected("netcaps").includes("extdisc"),
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
  // auto-managed SNI endpoints fold back into the primary-interface picker
  const allEps = (p.endpoints && p.endpoints.length) ? p.endpoints : null;
  const appEps = allEps
    ? allEps.filter((e) => (e.device_types || [])[0] !== SNI_NAME) : null;
  setEndpoints((appEps && appEps.length) ? appEps : profileDeviceTypes(p));
  setSelected("transport", p.transport || []);
  const assigned = (allEps || [])
    .filter((e) => (e.device_types || [])[0] === SNI_NAME)
    .map((e) => e.interface).filter(Boolean);
  refreshPrimary(transportFamilies().find((f) => !assigned.includes(f)));
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
  setSelected("flow", [p.commissioning_flow || "standard"]);
  const caps = [];
  if (p.tcp) caps.push("tcp");
  if (p.extended_discovery) caps.push("extdisc");
  setSelected("netcaps", caps);
  setSelected("role", [p.role || "commissionee"]);
  updateCodeLabel();
}

// The manual code's digit form follows the commissioning flow (spec 5.1.4).
function updateCodeLabel() {
  const btn = document.querySelector('#onboarding .opt[data-v="manual_pairing_code"]');
  if (btn) {
    const custom = selected("flow")[0] === "custom";
    btn.textContent = `Manual pairing code (${custom ? "21" : "11"})`;
  }
}

// A profile the engine would reject never reaches the engine: say what's wrong.
function validateProfile(p) {
  const errs = [];
  const dts = (p.endpoints || []).map((ep) => (ep.device_types || [])[0])
    .filter((n) => n && n !== SNI_NAME);   // auto SNI endpoints aren't the app
  if (!dts.length) errs.push("Add at least one application endpoint with a device type.");
  if (!p.transport.length) errs.push("Pick at least one transport.");
  // Multi-interface composition (Secondary Network Interface endpoints) is
  // auto-managed from Transport + Primary interface: always consistent here.
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

  // Spec versions come from the manifest (no per-version data fetched yet) --
  // each version's templates + datamodel are lazy-loaded on selection.
  const { versions } = await (await fetch(BASE + "web_bundle/versions.json")).json();
  const vsel = $("specVersion");
  versions.forEach((v) => vsel.add(new Option(`Matter ${v}`, v)));
  const session = loadSession();
  const savedV = session && session.profile && session.profile.spec_version;
  vsel.value = versions.includes(savedV) ? savedV : versions[versions.length - 1];
  await ensureVersion(vsel.value, status);
  loadDeviceTypes(vsel.value);
  vsel.addEventListener("change", async () => {
    await ensureVersion(vsel.value); loadDeviceTypes(vsel.value); markDirty();
  });

  if (session && session.profile) applyProfileToForm(session.profile);
  else setEndpoints([]);

  $("initOverlay").style.display = "none";
  setStepsEnabled(false);
  refreshValidity();
  // Restore a prior session straight to Review; a fresh visit starts on Describe.
  if (session && session.profile && validateProfile(readProfile()).length === 0)
    generate(session, true);
}

// Lazy-load a version's data (templates + datamodel) into the Pyodide FS once.
const loadedVersions = new Set();
async function ensureVersion(v, status) {
  if (!v || loadedVersions.has(v)) return;
  if (status) status.textContent = `Loading Matter ${v} data...`;
  const buf = await (await fetch(BASE + `web_bundle/data/${v}.zip`)).arrayBuffer();
  pyodide.unpackArchive(buf, "zip", { extractDir: "/bundle" });
  loadedVersions.add(v);
}

// ---- generate (runs automatically on every profile / claim change) ----
let genTimer = null;
function scheduleGenerate() {
  clearTimeout(genTimer);
  genTimer = setTimeout(() => generate(), 250);
}

async function generate(session, announce) {
  const profile = readProfile();
  const errs = validateProfile(profile);
  if (errs.length) {
    payload = null;
    setStepsEnabled(false);
    $("resultArea").innerHTML =
      `<div class="empty-state">${errs.map((e) => esc(e)).join("<br>")}</div>`;
    refreshValidity();
    return;
  }
  await ensureVersion(profile.spec_version);   // safety: data present before the engine runs
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

  // engine answers first, then the human's explicit overrides on top.
  // DECIDED items are engine-owned: a stale override from an earlier session
  // (when they were still togglable) must not stick to them, or the row would
  // show "Yes" while the derivation says No.
  answers = {}; touched = new Set();
  payload.items.forEach((it) => { answers[keyOf(it)] = it.answer; });
  payload.items.forEach((it) => {
    if (it.group === "decided") return;
    const k = keyOf(it);
    if (prevTouched.has(k) && prevAnswers[k] !== undefined) {
      answers[k] = prevAnswers[k];
      touched.add(k);
    }
  });
  render();
  setStepsEnabled(true);   // Review / Export steps become reachable
  dirty = false;
  saveSession();
  refreshValidity();
  if (announce) showView("review");   // Generate (or a restored session) -> Review screen
}

// ---- render (endpoint rail + plain-language rows) ----
// The shell (summary, stats, rail, panel) is built per engine run; the row body
// holds ONLY the active section's rows and is rebuilt on section switch.
// Four wizard stages. "review" (Design data model: Root Node + application
// endpoints) and "base" (Device questions: the node-wide Base facts) SHARE the
// review DOM -- the base stage is the same panel locked to the base section
// with the endpoint rail hidden. Base comes AFTER the data model on purpose:
// its claim-driven content (ICD, Diagnostic Logs, client capabilities) is
// settled by then, so the questionnaire the user sees is final.
const VIEWS = ["describe", "review", "base", "export"];
let wizStep = "describe";     // current wizard stage
function markStep(step) {
  const idx = VIEWS.indexOf(step);
  document.querySelectorAll("#stepper .rv-step").forEach((b) => {
    b.setAttribute("aria-current", String(b.dataset.step === step));
    b.classList.toggle("done", VIEWS.indexOf(b.dataset.step) < idx);
  });
}
// Later stages are only reachable once a payload exists.
function setStepsEnabled(on) {
  document.querySelectorAll("#stepper .rv-step").forEach((b) => {
    if (b.dataset.step !== "describe")
      b.setAttribute("aria-disabled", String(!on));
  });
}
// Show one wizard screen at a time. "base" renders inside #view-review.
function showView(name) {
  wizStep = name;
  const dom = name === "base" ? "review" : name;
  ["describe", "review", "export"].forEach((v) => {
    const el = $("view-" + v);
    if (el) el.hidden = v !== dom;
  });
  markStep(name);
  if ((name === "review" || name === "base") && payload) syncStage();
  if (name === "export") populateExport();
  window.scrollTo({ top: 0, behavior: "smooth" });
}
// Align the shared review shell with the wizard stage: the base stage locks
// the panel to the node-wide section and hides the endpoint rail; the design
// stage never shows the base section. Then render the rows.
function syncStage() {
  if (!payload) return;
  const inBase = wizStep === "base";
  if (inBase) {
    tab = "base";
  } else if (tab === "base") {
    tab = (payload.tabs.find((t) => t.id !== "base") || payload.tabs[0]).id;
  }
  const container = document.querySelector(".rv-review");
  if (container) container.classList.toggle("no-rail", inBase);
  const rail = $("rail");
  if (rail) rail.querySelectorAll("button").forEach((b) =>
    b.setAttribute("aria-current", String(b.dataset.tab === tab)));
  const toNext = $("toExport");
  if (toNext) toNext.textContent = inBase
    ? "Continue to Export →" : "Continue: Device questions →";
  renderRows();
}
// Fill the Export screen recap: counts + the files that will be produced.
function populateExport() {
  if (!payload) return;
  let yes = 0, no = 0, mine = 0;
  payload.items.forEach((it) => {
    if (answers[keyOf(it)] === "yes") yes++; else no++;
    // a mirrored twin follows its lead item's answer -- ONE user decision,
    // so it never counts a second time (keeps this tile equal to the
    // "My selections" review count below)
    if (isChanged(it) && !it.mirror_of) mine++;
  });
  $("exportStats").innerHTML =
    `<div class="rv-stat on"><span class="v">${yes}</span><span class="l">Supported (Yes)</span></div>
     <div class="rv-stat"><span class="v">${no}</span><span class="l">Not supported (No)</span></div>
     <div class="rv-stat mine"><span class="v">${mine}</span><span class="l">Changed by you</span></div>`;
  const eps = new Set();
  payload.tabs.forEach((t) => eps.add(t.id === "base" ? "0" : t.id));   // base + EP0 share endpoint0
  const files = [...eps].sort().map((e) => ({
    f: `endpoint${e}/`,
    d: e === "0" ? "Root Node + node-wide (Base)"
                 : ((payload.tabs.find((t) => t.id === e) || {}).label || ""),
  }));
  files.push({ f: "PIXIT_CHECKLIST.md", d: "test-bed values to fill in the CSA tool" });
  $("exportFiles").innerHTML = files.map((x) =>
    `<li><span class="fi">${esc(x.f)}</span><small>${esc(x.d)}</small></li>`).join("");
  buildReviewArea();
  renderScaffold();
}

// ---- Export-stage answer review (collapsed by default) ----
// After the data model and device questions are complete, the user can
// double-check what they selected: "My selections" (everything they switched
// on, plus its spec consequences) or "All optional questions" with each
// current answer -- grouped by section, then category/cluster. Read-only:
// changes happen on the earlier stages.
function buildReviewArea() {
  const area = $("reviewArea");
  if (!area || !payload) return;
  const wasOpen = !!area.querySelector("details[open]");
  // the reviewable pool = every visible optional question (mirror twins fold
  // into their lead; items not applicable right now are not questions)
  const pool = payload.items.filter((it) =>
    it.group === "manual" && !it.mirror_of && isApplicable(it));
  const mine = pool.filter((it) => isChanged(it));
  const list = revShowAll ? pool : mine;

  const byTab = new Map();
  list.forEach((it) => {
    if (!byTab.has(it.tab)) byTab.set(it.tab, new Map());
    const byCl = byTab.get(it.tab);
    if (!byCl.has(it.cluster)) byCl.set(it.cluster, []);
    byCl.get(it.cluster).push(it);
  });
  const secLabel = (t) => {
    if (t === "base") return "Device questions (node-wide)";
    const tb = payload.tabs.find((x) => x.id === t) || { label: `Endpoint ${t}` };
    return `${tb.label} — Endpoint ${t}`;
  };
  const secs = [...byTab.entries()].map(([t, byCl]) => `
    <div class="rev-sec"><div class="rev-sech">${esc(secLabel(t))}</div>
      ${[...byCl.entries()].map(([cl, its]) => `
        <div class="rev-cl"><span class="rev-clname">${esc(cl)}</span>
          <span class="rev-items">${its.map((it) => `
            <span class="rev-item ${answers[keyOf(it)] === "yes" ? "yes" : "no"}"
              title="${esc(it.question || "")}&#10;${esc(it.code)}">${esc(it.name || it.question || it.code)}</span>`).join("")}
          </span></div>`).join("")}
    </div>`).join("");

  area.innerHTML = `
    <details class="rev"${wasOpen ? " open" : ""}>
      <summary><span class="rv-caret" aria-hidden="true">▾</span> Review your answers
        <span class="rev-cnt">${mine.length} selected by you</span></summary>
      <div class="rev-tools">
        <div class="rv-seg" id="revSeg">
          <button data-a="mine" aria-pressed="${!revShowAll}">My selections (${mine.length})</button>
          <button data-a="all" aria-pressed="${revShowAll}">All optional questions (${pool.length})</button>
        </div>
        <span class="rev-note">Read-only — use the earlier steps to change anything.</span>
      </div>
      ${secs || `<div class="rev-empty">Nothing selected — every optional question exports as “No”.</div>`}
    </details>`;
  area.querySelectorAll("#revSeg button").forEach((b) =>
    b.addEventListener("click", () => {
      revShowAll = b.dataset.a === "all";
      buildReviewArea();
      const d = area.querySelector("details");
      if (d) d.open = true;
    }));
}

// Every optional element the user explicitly switched ON (touched + yes),
// grouped per endpoint tab, for the scaffold: features, cluster sides, AND
// optional attributes/commands. Unlike claimsByTab (which keeps only
// features/sides/MCORE, the codes the PICS engine re-seeds from), this passes
// everything so the generated code adds the exact optional elements you picked.
function optionalClaimsByTab() {
  const out = {};
  touched.forEach((k) => {
    if (answers[k] !== "yes") return;
    const [t, code] = splitKey(k);
    (out[t] ??= []).push(code);
  });
  return out;
}

// Generate the esp-matter data-model code with the SAME engine the CLI uses, so
// the browser and `gen-scaffold` emit identical code. Optional elements the user
// switched on ride along per endpoint and show as add/create guidance.
// Pure-Python renderer (no Jinja2), so nothing extra loads in the browser.
function renderScaffold() {
  const pre = $("scaffoldCode"), note = $("scaffoldNote");
  if (!pre || !payload) return;
  scaffoldSnippet = "";
  // Opt-out: the code is only for esp-matter users; skip the (synchronous)
  // generation entirely when the box is unticked.
  const gen = $("genCode");
  const body = $("scaffoldBody");
  if (gen && body) {
    body.hidden = !gen.checked;
    if (!gen.checked) return;
  }
  try {
    const res = JSON.parse(webapp.generate_scaffold_json(
      JSON.stringify(payload.profile), JSON.stringify(optionalClaimsByTab())));
    scaffoldSnippet = res.snippet;
    pre.querySelector("code").textContent = res.snippet;
    renderScaffoldSource(res);
    renderScaffoldNote(res, note);
  } catch (err) {
    scaffoldSnippet = "";
    pre.querySelector("code").textContent = "// Could not generate code: " + (err.message || err);
    note.hidden = true;
    console.error(err);
  }
}

// A short caveat line ONLY when the generated code needs a second look: it used
// the nearest available signatures (no released component for this Matter version
// yet) or fell back to placeholders. For an exact match there's nothing to say,
// so the line is hidden. (No CLI instructions here -- this is the browser UI.)
function renderScaffoldSource(res) {
  const el = $("scaffoldSource");
  if (!el) return;
  const src = res.knowledge_source || "";
  const nearest = !!res.exact && /nearest/i.test(src);
  el.classList.remove("exact");                 // caveat lines are amber
  if (res.exact && !nearest) {                  // perfect match -> no note needed
    el.hidden = true;
    el.innerHTML = "";
    return;
  }
  el.hidden = false;
  if (nearest) {
    const m = src.match(/esp_matter\s+([0-9.]+)/);
    const ver = m ? m[1] : "the nearest release";
    el.innerHTML = `<span class="src-dot"></span>Generated with <b>esp_matter ${esc(ver)}</b> `
      + `signatures (closest available — no released component for this Matter version yet); `
      + `double-check before building.`;
  } else {
    el.innerHTML = `<span class="src-dot"></span>Some arguments are placeholders `
      + `(<code>/* … */</code>) — fill in the values before building.`;
  }
}

// Recap of what the generated CODE adds, grouped per endpoint (device type) then
// cluster -- so it's clear which endpoint a shared cluster (Descriptor, On/Off)
// belongs to. This counts data-model elements the code emits, which is a
// different thing from the "Changed by you" PICS-answer stat (node-level/MCORE
// answers and disabled items don't produce data-model code), so it's worded to
// say so. Empty -> hide the note entirely.
function renderScaffoldNote(res, note) {
  const endpoints = res.endpoints || [];
  const labelOf = {};
  endpoints.forEach((e) => { labelOf[e.endpoint] = e.label || (e.device_types || []).join(" + "); });
  // "added" = resolved elements the code actually emits (already per-endpoint);
  // flatten with their endpoint so both lists render the same way.
  const added = endpoints.flatMap((e) => (e.optional || []).map((o) => ({ ...o, endpoint: e.endpoint })));
  const unresolved = res.unresolved || [];
  if (!added.length && !unresolved.length) { note.hidden = true; note.innerHTML = ""; return; }

  // render [{endpoint, cluster, name, kind}] grouped Endpoint -> cluster -> chips
  const sections = (items) => {
    const byEp = new Map();
    items.forEach((o) => { if (!byEp.has(o.endpoint)) byEp.set(o.endpoint, []); byEp.get(o.endpoint).push(o); });
    return [...byEp.entries()].map(([ep, its]) => {
      const groups = new Map();
      its.forEach((o) => { if (!groups.has(o.cluster)) groups.set(o.cluster, []); groups.get(o.cluster).push(o); });
      const rows = [...groups.entries()].map(([cl, els]) =>
        `<div class="sn-row"><span class="sn-cluster">${esc(cl)}</span><span class="sn-els">`
        + els.map((o) => `<span class="sn-chip" data-kind="${esc(o.kind)}" title="${esc(o.kind)}">${esc(o.name)}</span>`).join("")
        + `</span></div>`).join("");
      return `<div class="sn-ep"><div class="sn-eptitle">Endpoint ${ep}`
        + `<span class="sn-dt">${esc(labelOf[ep] || "")}</span></div>${rows}</div>`;
    }).join("");
  };

  let html = "";
  if (added.length) {
    html += `<div class="sn-head">Optional elements this code adds`
      + ` <span class="sn-sub">(${added.length})</span></div>${sections(added)}`;
  }
  if (unresolved.length) {   // kept in the code as // comments; list the actual items here
    html += `<div class="sn-omit"><div class="sn-head">Add manually`
      + ` <span class="sn-sub">(no esp_matter API — left as <code>//</code> comments)</span></div>`
      + sections(unresolved) + `</div>`;
  }
  note.hidden = false;
  note.innerHTML = html;
}

function downloadScaffold() {
  if (!scaffoldSnippet) return;
  const blob = new Blob([scaffoldSnippet], { type: "text/x-c++src" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "app_data_model.cpp";
  a.click();
  URL.revokeObjectURL(a.href);
}

async function copyScaffold() {
  if (!scaffoldSnippet) return;
  const btn = $("copyCode");
  try {
    await navigator.clipboard.writeText(scaffoldSnippet);
    const was = btn.textContent; btn.textContent = "Copied ✓";
    setTimeout(() => { btn.textContent = was; }, 1400);
  } catch (e) { /* clipboard blocked: the code is still visible to select manually */ }
}

function render() {
  const perTab = {};
  payload.items.forEach((it) => { perTab[it.tab] = (perTab[it.tab] || 0) + 1; });
  if (!payload.tabs.some((t) => t.id === tab)) tab = payload.tabs[0].id;
  if (wizStep !== "base") markStep("review");

  // the rail lists only the data-model sections; the node-wide Base section
  // is its own wizard stage (Device questions), never a rail entry
  const rail = payload.tabs.filter((t) => t.id !== "base").map((t) =>
    `<button data-tab="${esc(t.id)}" aria-current="${t.id === tab}">
       <span class="epi">${esc(t.id)}</span>
       <span class="rt">${esc(t.label)}<small>${esc(t.caption || "")}</small></span>
       <span class="cnt">${perTab[t.id] || 0}</span>
     </button>`).join("");

  // No stats tiles here: the Yes/No/Changed recap lives on the Export stage
  // only -- mid-flow the counts churn on every claim and read as noise.
  $("resultArea").innerHTML = `
    <div class="rv-review">
      <nav class="rv-rail" id="rail"><div class="rg">Sections</div>${rail}</nav>
      <div class="rv-panel" id="panel">
        <div class="rv-ptop">
          <h3 id="panelTitle"></h3><span style="flex:1"></span>
          <div class="rv-seg" id="modeSeg" role="group" aria-label="View mode">
            <button data-m="simple" aria-pressed="${mode === "simple"}"
              title="Only the choices that need you — quick chip selection">Simple</button>
            <button data-m="advanced" aria-pressed="${mode === "advanced"}"
              title="Every PICS question (Mandatory + Optional) with Yes/No answers">Advanced</button>
          </div>
        </div>
        <div class="rv-ptop" style="border-top:none">
          <div class="rv-searchbox">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>
            <input id="q" type="text" placeholder="Search questions or PICS codes" aria-label="Search">
          </div>
          <div class="rv-seg adv-only" id="grpSeg">
            <button data-g="decided" aria-pressed="${grp === "decided"}"><span class="sw" style="background:var(--on)"></span>Mandatory <span id="gc-decided"></span></button>
            <button data-g="manual" aria-pressed="${grp === "manual"}"><span class="sw" style="background:var(--review)"></span>Optional <span id="gc-manual"></span></button>
          </div>
          <label class="rv-detail-t adv-only"><input type="checkbox" id="showDetails"> Show details</label>
        </div>
        <div id="tb"></div>
        <div id="noMatchHint" class="rv-hint" hidden></div>
        <div class="rv-footbar">
          <span class="muted">Answers are saved as you go.</span>
          <span style="flex:1"></span>
          <button class="btn ghost" id="clearBtn">Clear my answers</button>
          <button class="btn" id="toExport">Continue to Export →</button>
        </div>
      </div>
    </div>`;

  $("q").value = searchQ;
  wireShell();
  syncStage();
}

// Row body for the ACTIVE section only. Dispatches on the presentation mode:
// simple = chip cards of the live optional choices; advanced = every question
// (both groups; the Mandatory/Optional switch hides one).
function renderRows() {
  const t = payload.tabs.find((x) => x.id === tab);
  // user-facing name for the node-wide section ("Base PICS" is spec jargon)
  $("panelTitle").textContent = tab === "base" ? "Device questions" : (t ? t.label : "");
  $("panel").classList.toggle("mode-simple", mode === "simple");
  if (mode === "simple") { renderSimpleRows(); return; }
  const clColor = {};
  let ci = 0;
  const colorOf = (cl) => (clColor[cl] ??= CLUSTER_PALETTE[ci++ % CLUSTER_PALETTE.length]);

  const html = [];
  ["decided", "manual"].forEach((g) => {
    const members = payload.items
      .map((it, i) => ({ it, i }))
      .filter(({ it }) => it.tab === tab && it.group === g);
    // Spec-optional clusters lead the Optional view as a CATALOG of toggle
    // chips -- visible at a glance, no scrolling past every mandatory
    // cluster's options. Their gateway rows don't repeat in the list below;
    // an enabled cluster's section (pre-filled + questions) appears there.
    if (g === "manual") {
      const gws = members.filter(({ it }) => it.opt_cluster && !it.parent)
        .sort((a, b) => chipLabel(a.it).localeCompare(chipLabel(b.it)));
      if (gws.length) {
        const chips = gws.map(({ it }) => {
          const on = answers[keyOf(it)] === "yes";
          return `<button class="oc-chip" data-k="${esc(keyOf(it))}" data-code="${esc(it.code)}"
            aria-pressed="${on}" title="${esc(it.why || "")}">${esc(chipLabel(it))}</button>`;
        }).join("");
        html.push(`<div class="rv-optcat">
          <div class="oc-head">Optional clusters
            <span class="oc-sub">the spec allows these on this endpoint — select the ones your product implements</span></div>
          <div class="oc-chips">${chips}</div></div>`);
      }
    }
    const order = [];
    const byCl = new Map();
    members.forEach((m) => {
      // An UNSELECTED optional cluster exists only as its catalog chip. Once
      // selected, its gateway question ALSO leads the cluster's section below
      // (answered Yes), so every counted item is a visible row.
      if (m.it.opt_cluster && !m.it.parent && answers[keyOf(m.it)] !== "yes") return;
      if (!byCl.has(m.it.cluster)) { byCl.set(m.it.cluster, []); order.push(m.it.cluster); }
      byCl.get(m.it.cluster).push(m);
    });
    order.forEach((cl) => {
      const rows = byCl.get(cl);
      const key = `${tab}|${g}|${cl}`;
      const color = colorOf(cl);
      // whole cluster is spec-optional for this endpoint (not in the baseline):
      // badge the section so it reads as "yours to claim", not tool-selected
      const optBadge = rows.some(({ it }) => it.opt_cluster)
        ? `<span class="rv-optcl">Optional cluster</span>` : "";
      html.push(`<div class="rv-clhead ${collapsed.has(key) ? "collapsed" : ""}" data-key="${esc(key)}"
        role="button" tabindex="0" aria-expanded="${!collapsed.has(key)}">
        <span class="rv-caret" aria-hidden="true">▾</span>
        <span class="rv-cldot" style="background:${color}"></span>${esc(cl)}${optBadge}<span class="cc">${rows.length}</span></div>`);
      rows.forEach(({ it, i }) => {
        const a = answers[keyOf(it)];
        const roleTok = it.code.startsWith("MCORE.") ? "" : it.code.split(".")[1];
        const side = roleTok === "S" ? "server" : roleTok === "C" ? "client" : "";
        const badge = side ? `<span class="rv-side ${side}">${side === "server" ? "Server" : "Client"}</span>` : "";
        // A DECIDED answer is derived from the inputs / role / spec conformance:
        // read-only everywhere. Node-level items change via the governing input
        // on the Describe step; cluster items follow the spec for the declared
        // device (an exactly-one feature group, a transport-gated feature, ...).
        const locked = it.group === "decided";
        // The tooltip lives on the CONTAINER (with pointer-events:none on the
        // disabled buttons): browsers don't reliably fire hover on disabled
        // elements, so a per-button title would often never show.
        const lockTip = it.tab === "base"
          ? "The tool derived this from your inputs. To change it, adjust the inputs in Step 1 (Describe)."
          : "The spec decides this for your device. To change it, adjust the inputs or the selections that drive it.";
        const lockWrap = locked ? ` data-tip="${esc(lockTip)}"` : "";
        const lockAttr = locked ? " disabled" : "";
        html.push(`<div class="rv-qrow ${it.parent ? "child" : ""} ${isChanged(it) ? "changed" : ""}"
            data-i="${i}" data-tab="${esc(it.tab)}" data-group="${esc(it.group)}" data-key="${esc(key)}"
            data-code="${esc(it.code).toLowerCase()}" data-q="${esc((it.question || it.code)).toLowerCase()}">
          <div class="rv-qmain">
            <div class="rv-qtext">${esc(it.question || it.code)}${badge}${
              it.opt_cluster && !it.parent
                ? `<span class="rv-optcl">Optional</span>` : ""}</div>
            ${it.why ? `<div class="rv-why">${esc(it.why)}</div>` : ""}
            <div class="rv-meta"><span class="code">${esc(it.code)}</span><span>${esc(it.conformance)}</span></div>
          </div>
          <div class="rv-yn ${locked ? "locked" : ""}" data-k="${esc(keyOf(it))}" data-code="${esc(it.code)}"${lockWrap}>
            <button class="yes ${a === "yes" ? "act" : ""}" data-a="yes"${lockAttr} aria-label="Yes: ${esc(it.code)}">Yes</button>
            <button class="no ${a === "no" ? "act" : ""}" data-a="no"${lockAttr} aria-label="No: ${esc(it.code)}">No</button>
          </div></div>`);
      });
    });
  });
  $("tb").innerHTML = html.join("");
  wireRows();
  wireCatalog();
  applyFilter();
}

// ---- simple view: ZAP-style -- a clean cluster list, details in a dialog ----
// First glance = one short list per section. Each cluster is ONE row showing
// only its name, whether it is included ("Required" badge, or an Include
// switch for spec-optional clusters) and how many optional choices it holds.
// ALL detail lives in a per-cluster configure dialog (like ZAP's cluster
// page): features, attributes, commands, client role -- each one a labelled
// toggle. The Base tab is the same list with one row per question topic.
// Toggles carry the exact same answer/claim semantics as the advanced Yes/No
// rows: features / cluster sides / MCORE claims re-run the engine, so their
// consequences appear immediately.
let modalName = null;         // row whose configure dialog is open (null = none)
let modalDetails = false;     // dialog "Show details": full question + PICS code

// Build the table model for the active tab from the payload.
// A row = a cluster (endpoint tabs) or a question topic (Base tab):
//   required -- the tool already included this cluster (has decided items);
//   gateway  -- the spec-optional cluster's claimable side (X.S / X.C item);
//   items    -- the cluster's elements in payload (template) order, each
//               {it, locked}: locked rows are engine-settled (mandatory
//               elements, claim-derived inclusions, spec-excluded items) and
//               display as read-only toggles; unlocked rows are the user's
//               live optional choices.
function simpleRowsData() {
  const isBase = tab === "base";
  const order = [];
  const rows = new Map();
  const gwRow = {};             // gateway code -> row name (routes its sub-items)
  const rowOf = (name) => {
    if (!rows.has(name)) {
      rows.set(name, { name, required: false, gateway: null, items: [] });
      order.push(name);
    }
    return rows.get(name);
  };
  const strip = (cl) => cl.replace(/\s+Cluster$/i, "");
  const gwOf = (it) => it.code.split(".").slice(0, 2).join(".");
  let decidedN = 0;
  payload.items.forEach((it) => {
    if (it.tab !== tab) return;
    if (it.group === "decided") {
      decidedN++;
      if (isBase) return;   // node-wide derived answers stay in the banner
      // Engine-settled element: shown read-only in its cluster's dialog. For
      // a spec-optional cluster only while that cluster is actually included.
      let name = strip(it.cluster);
      if (it.opt_cluster) {
        name = gwRow[gwOf(it)] || name;
        if (answers[`${tab}|${gwOf(it)}`] !== "yes") return;
      }
      const r = rowOf(name);
      if (!it.opt_cluster) r.required = true;
      r.items.push({ it, locked: true });
      return;
    }
    // the whole-cluster choice (the Include switch), never a dialog row
    if (!isBase && it.opt_cluster && !it.parent && GATEWAY_RE.test(it.code)) {
      const r = rowOf(chipLabel(it));
      r.gateway = it;
      gwRow[it.code] = r.name;
      return;
    }
    if (!isApplicable(it)) return;   // revealed only under its claimed parent
    if (it.mirror_of) return;        // mirrored twin: asked once via its lead item
    let name = isBase ? it.cluster : strip(it.cluster);
    if (it.opt_cluster) {   // sub-item of a claimed optional cluster: its gateway's row
      name = gwRow[gwOf(it)] || name;
    }
    if (it.needs_you) {
      // The engine pre-filled Yes as a spec consequence of ANOTHER claim
      // (CheckInProtocol under LITS) and the user never touched it: shown
      // read-only Required -- withdrawing the parent claim releases it.
      const derived = it.answer === "yes" && !touched.has(keyOf(it));
      rowOf(name).items.push({ it, locked: derived });
    } else if (!isBase && answers[keyOf(it)] === "yes") {
      // claim-derived mandatory element: included automatically, read-only
      rowOf(name).items.push({ it, locked: true });
    }
    // manual, not live, answered No: not applicable right now -> hidden
  });
  // included clusters first (payload order), then the spec-optional offers A-Z
  const req = order.filter((n) => !rows.get(n).gateway);
  const opt = order.filter((n) => rows.get(n).gateway).sort((a, b) => a.localeCompare(b));
  return { order: [...req, ...opt], rows, decidedN, isBase };
}

function renderSimpleRows() {
  const { order, rows, decidedN, isBase } = simpleRowsData();
  const clColor = {};
  let ci = 0;
  const colorOf = (cl) => (clColor[cl] ??= CLUSTER_PALETTE[ci++ % CLUSTER_PALETTE.length]);

  const html = [];
  let unitsTotal = 0;   // question units the table shows (a grouped family = 1)

  const head = isBase
    ? `<span>Topic</span><span>Questions</span><span>Selected</span><span></span>`
    : `<span>Cluster</span><span>Included</span><span>Options</span><span></span>`;
  const body = [];
  order.forEach((name) => {
    const r = rows.get(name);
    const opts = r.items.filter((x) => !x.locked);
    const autoN = r.items.length - opts.length;
    const selN = opts.filter(({ it }) => answers[keyOf(it)] === "yes").length;
    // everything searchable about this row rides along for the filter
    const searchText = [name, ...r.items.map(({ it }) =>
      `${it.name || ""} ${it.question || ""} ${it.code}`)].join(" ").toLowerCase();
    const clickable = r.items.length > 0;
    const pill = selN ? `<span class="st-selpill">${selN} selected</span>` : "";
    let cells;
    if (isBase) {
      // a grouped family (same "ask") reads as ONE question with options
      const families = new Set();
      let qn = 0;
      opts.forEach(({ it }) => { if (it.ask) families.add(it.ask); else qn++; });
      qn += families.size;
      unitsTotal += qn;
      cells = `
        <div class="st-name"><span class="rv-cldot" style="background:${colorOf(name)}"></span>${esc(name)}</div>
        <div class="st-dim">${qn} question${qn === 1 ? "" : "s"}</div>
        <div>${pill || `<span class="st-dash">—</span>`}</div>
        <div class="st-chev">${clickable ? "›" : ""}</div>`;
    } else {
      // No gateway and no decided items happens for extra test-plan question
      // groups of an included cluster (Group Communication rides on ACL): the
      // template IS exported, so it reads as included -- never a switch.
      const included = r.required || !r.gateway
        ? `<span class="st-req">✓ Required</span>`
        : `<span class="tgl" title="${esc(r.gateway.why || "")}">
             <input type="checkbox" data-k="${esc(keyOf(r.gateway))}" data-code="${esc(r.gateway.code)}"
               data-row="${esc(name)}" aria-label="Include ${esc(name)}"${answers[keyOf(r.gateway)] === "yes" ? " checked" : ""}><i></i></span>`;
      const optTxt = opts.length
        ? `<span class="st-dim">${opts.length} option${opts.length === 1 ? "" : "s"}</span> ${pill}`
        : autoN
          ? `<span class="st-dim">${autoN} element${autoN === 1 ? "" : "s"} auto-included</span>`
          : `<span class="st-dash">—</span>`;
      // spec-optional clusters carry an explicit text badge (same as the
      // advanced view) -- the Include switch alone is easy to miss
      const optBadge = r.gateway ? `<span class="rv-optcl">Optional</span>` : "";
      cells = `
        <div class="st-name"><span class="rv-cldot" style="background:${colorOf(name)}"></span>${esc(name)}${optBadge}</div>
        <div>${included}</div>
        <div>${optTxt}</div>
        <div class="st-chev">${clickable ? "›" : ""}</div>`;
    }
    body.push(`<div class="st-row${clickable ? " click" : ""}" data-row="${esc(name)}"
      data-search="${esc(searchText)}">${cells}</div>`);
  });
  // The banner reconciles every number on screen: total raw PICS items on
  // this section, how many the engine answered, and how the open remainder
  // condenses into the question units the table shows (duplicates asked once,
  // families as one multi-select, follow-ups only when they apply).
  const totalN = payload.items.filter((it) => it.tab === tab).length;
  const manualN = totalN - decidedN;
  const banner = isBase
    ? `<b>${totalN} PICS items in this section — ${decidedN} answered automatically</b>
       from your device description. The remaining ${manualN} are optional and condense
       into the <b>${unitsTotal} question${unitsTotal === 1 ? "" : "s"}</b> below (the same
       fact is asked once; follow-ups appear only when they apply). Anything left
       unticked is exported as “No”.`
    : `<b>${totalN} PICS items on this section — ${decidedN} answered automatically</b>
       from your device description; the rest follow from what you include below.
       Anything left off is exported as “No”.`;
  html.push(`<div class="sv-banner"><span class="ic">✓</span><div>${banner}
      <button class="linklike" id="seeAll">See every question</button></div></div>`);
  html.push(body.length
    ? `<div class="st"><div class="st-head">${head}</div>${body.join("")}</div>`
    : `<div class="rv-hint">No optional choices on this section — everything
      here was answered automatically from your inputs.</div>`);

  $("tb").innerHTML = html.join("");
  const seeAll = $("seeAll");
  if (seeAll) seeAll.addEventListener("click", () => setMode("advanced"));
  wireSimpleTable();
  recount();
  applyFilter();
  renderClusterModal();   // refresh the open configure dialog after a re-run
}

// wire the simple list: a row opens its configure dialog; the Include switch
// claims/withdraws the spec-optional cluster without opening it.
function wireSimpleTable() {
  $("tb").querySelectorAll(".st-row.click").forEach((row) =>
    row.addEventListener("click", (e) => {
      if (e.target.closest(".tgl")) return;   // the Include switch, not "open"
      modalName = row.dataset.row;
      renderClusterModal();
    }));
  $("tb").querySelectorAll(".st-row .tgl input").forEach((inp) =>
    inp.addEventListener("change", () => {
      applyToggle(inp);
      // just included: open the cluster's options once the engine returns
      // (renderSimpleRows -> renderClusterModal); switched off: keep it shut.
      modalName = inp.checked ? inp.dataset.row : null;
    }));
}

// One option/Include control flipped -- identical claim semantics to the
// advanced rows. Returns true when the flip re-runs the engine.
function applyToggle(inp) {
  return applyAnswer(inp.dataset.k, inp.dataset.code, inp.checked);
}
function applyAnswer(k, code, on) {
  answers[k] = on ? "yes" : "no";
  touched.add(k);
  // A mirrored Base fact (the same DNS-SD question in the DD and SC test
  // plans) is asked once -- its twin code follows the answer automatically.
  const [tb] = splitKey(k);
  const src = payload.items.find((x) => x.tab === tb && x.code === code);
  ((src && src.mirrors) || []).forEach((m) => {
    const mk = `${tb}|${m}`;
    answers[mk] = answers[k];
    touched.add(mk);
  });
  // Un-claiming a parent (Include / feature -> off) withdraws everything
  // revealed under it, on the same endpoint (mirrors the advanced rows).
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
  if (FEATURE_RE.test(code) || GATEWAY_RE.test(code) || code.startsWith("MCORE.")) {
    scheduleGenerate();
    return true;
  }
  return false;
}

// ---- the per-cluster configure dialog (ZAP's cluster page, simplified) ----
const _SECTION_ORDER = ["Features", "Attributes", "Commands", "Events",
                        "Other options", "Client role"];
function sectionOf(it) {
  if (FEATURE_RE.test(it.code)) return "Features";
  const parts = it.code.split(".");
  if (parts[1] === "C") return "Client role";
  const tag = (parts[2] || "")[0];
  return tag === "A" ? "Attributes" : tag === "C" ? "Commands"
    : tag === "E" ? "Events" : "Other options";
}

function closeClusterModal(rerender) {
  modalName = null;
  const el = $("svModal");
  if (el) el.remove();
  if (rerender) renderSimpleRows();   // the list's counts reflect the dialog
}

function renderClusterModal() {
  if (!modalName) { const el = $("svModal"); if (el) el.remove(); return; }
  const { rows, isBase } = simpleRowsData();
  const r = rows.get(modalName);
  if (!r) { closeClusterModal(false); return; }
  const t = payload.tabs.find((x) => x.id === tab);
  const selN = r.items.filter((x) => !x.locked && answers[keyOf(x.it)] === "yes").length;

  // Dialogs show the item's short label -- element name for cluster options,
  // boilerplate-stripped question for Base facts; an item with no confident
  // short label keeps the question as its label. "Show details" reveals the
  // full question + PICS code under each row (also a hover tooltip).
  // Locked rows are engine-settled: mandatory / claim-derived elements show a
  // read-only ON toggle ("Required"), spec-excluded items a read-only OFF one.
  const rowHtml = ({ it, locked }) => {
    const on = answers[keyOf(it)] === "yes";
    const label = it.name || it.question || it.code;
    const detail = (it.name && it.question ? `${it.question} · ` : "") + it.code
      + (it.mirrors ? ` · also answers ${it.mirrors.join(", ")}` : "");
    const tag = !locked ? ""
      : on ? `<span class="sm-tag">Required</span>`
           : `<span class="sm-tag off">Not applicable</span>`;
    return `
    <label class="sm-row${locked ? " locked" : ""}"
      title="${esc(it.question || "")}${locked && it.why ? `&#10;${esc(it.why)}` : ""}&#10;${esc(it.code)}">
      <span class="sm-main">
        <span class="sm-name">${esc(label)}${tag}</span>
        <span class="sm-q">${esc(detail)}</span>
      </span>
      <span class="tgl"><input type="checkbox" data-k="${esc(keyOf(it))}"
        data-code="${esc(it.code)}"${locked ? " disabled" : ""}${on ? " checked" : ""}><i></i></span>
    </label>`;
  };

  // A parallel Base family (same "ask") folds into ONE multi-select question:
  // a single title with one option chip per member. Each chip IS its PICS
  // item -- selecting it answers exactly that item, nothing is inferred.
  const groupHtml = (members) => {
    const first = members[0].it;
    const chips = members.map(({ it }) => {
      const on = answers[keyOf(it)] === "yes";
      return `<button class="sm-optchip" data-k="${esc(keyOf(it))}" data-code="${esc(it.code)}"
        aria-pressed="${on}" title="${esc(it.question || "")}&#10;${esc(it.code)}">${esc(it.option || it.name || it.code)}</button>`;
    }).join("");
    let prefix = members[0].it.code;
    members.forEach(({ it }) => {
      while (!it.code.startsWith(prefix)) prefix = prefix.slice(0, -1);
    });
    return `<div class="sm-group">
      <span class="sm-main"><span class="sm-name">${esc(first.ask)}</span>
        <span class="sm-q">select all that apply · ${esc(prefix)}…</span></span>
      <div class="sm-opts">${chips}</div></div>`;
  };

  let bodyHtml;
  if (!r.items.length) {
    bodyHtml = `<div class="sm-empty">Nothing to configure here yet.</div>`;
  } else if (isBase) {
    const parts = [];
    const grouped = new Set();
    r.items.forEach((x) => {
      const ask = x.it.ask;
      if (!ask) { parts.push(rowHtml(x)); return; }
      if (grouped.has(ask)) return;   // family renders once, where it starts
      grouped.add(ask);
      parts.push(groupHtml(r.items.filter((y) => y.it.ask === ask)));
    });
    bodyHtml = parts.join("");
  } else {
    const sections = new Map();
    r.items.forEach((x) => {
      const s = sectionOf(x.it);
      if (!sections.has(s)) sections.set(s, []);
      sections.get(s).push(x);
    });
    bodyHtml = _SECTION_ORDER.filter((s) => sections.has(s)).map((s) =>
      `<div class="sm-sect">${s}</div>` + sections.get(s).map(rowHtml).join("")).join("");
  }

  let overlay = $("svModal");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.id = "svModal";
    document.body.appendChild(overlay);
    overlay.addEventListener("click", (e) => { if (e.target === overlay) closeClusterModal(true); });
  }
  // an engine re-run re-renders the open dialog: keep the reading position
  const prevScroll = overlay.querySelector(".sm-body")?.scrollTop || 0;
  overlay.innerHTML = `
    <div class="modal sm-modal${modalDetails ? " details" : ""}" role="dialog" aria-label="${esc(modalName)} options">
      <div class="sm-head">
        <div><h3>${esc(modalName)}${r.gateway ? ` <span class="rv-optcl">Optional cluster</span>` : ""}</h3>
          <div class="sm-sub">${esc(t ? t.label : "")}${isBase ? "" : " — switch on what your product supports"}</div></div>
        <span class="sm-count" id="smCount">${selN} selected</span>
        <button class="sm-close" aria-label="Close" title="Close">✕</button>
      </div>
      <div class="sm-body">${bodyHtml}</div>
      <div class="modal-actions sm-foot">
        <label class="sm-detail"><input type="checkbox" id="smDetails"${modalDetails ? " checked" : ""}>
          Show details</label>
        <span style="flex:1"></span>
        <button class="btn" id="smDone">Done</button>
      </div>
    </div>`;
  overlay.querySelector(".sm-body").scrollTop = prevScroll;
  overlay.querySelector(".sm-close").addEventListener("click", () => closeClusterModal(true));
  overlay.querySelector("#smDone").addEventListener("click", () => closeClusterModal(true));
  overlay.querySelector("#smDetails").addEventListener("change", (e) => {
    modalDetails = e.target.checked;
    overlay.querySelector(".sm-modal").classList.toggle("details", modalDetails);
  });
  overlay.querySelectorAll(".sm-row .tgl input").forEach((inp) =>
    inp.addEventListener("change", () => {
      applyToggle(inp);   // a claim re-runs the engine; this dialog refreshes
      const n = [...overlay.querySelectorAll(".sm-row .tgl input:not(:disabled)")]
        .filter((x) => x.checked).length
        + overlay.querySelectorAll('.sm-optchip[aria-pressed="true"]').length;
      const c = $("smCount");
      if (c) c.textContent = `${n} selected`;
    }));
  // multi-select option chips: pressed = Yes on that chip's own PICS item
  overlay.querySelectorAll(".sm-optchip").forEach((b) =>
    b.addEventListener("click", () => {
      const on = b.getAttribute("aria-pressed") === "true";
      b.setAttribute("aria-pressed", String(!on));
      applyAnswer(b.dataset.k, b.dataset.code, !on);
      // MCORE claims re-run the engine; the dialog re-renders with counts
    }));
}

// search filter for the simple list: each row carries its full searchable text
// (name + every option label, question, and PICS code) in data-search.
function applySimpleFilter() {
  const q = searchQ.toLowerCase();
  let visible = 0;
  $("tb").querySelectorAll(".st-row").forEach((row) => {
    const m = !q || (row.dataset.search || "").includes(q);
    row.style.display = m ? "" : "none";
    if (m) visible++;
  });
  const headEl = $("tb").querySelector(".st-head");
  if (headEl) headEl.style.display = visible ? "" : "none";
  const hint = $("noMatchHint");
  if (!hint) return;
  hint.hidden = !(q && visible === 0);
  if (!hint.hidden) {
    hint.textContent = "Nothing matches here — try another section, or the Advanced view "
      + "(it includes every question, not just the optional choices).";
  }
}

// switch between the simple (table) and advanced (all questions) presentations
function setMode(m) {
  if (mode === m) return;
  mode = m;
  localStorage.setItem(MODE_KEY, m);
  const seg = $("modeSeg");
  if (seg) seg.querySelectorAll("button").forEach((x) =>
    x.setAttribute("aria-pressed", String(x.dataset.m === m)));
  renderRows();
}

// wire the shell controls (rail, view switch, search, details, edit) -- per render
function wireShell() {
  $("rail").querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => {
      tab = b.dataset.tab;
      $("rail").querySelectorAll("button").forEach((x) => x.setAttribute("aria-current", String(x === b)));
      renderRows();
    }));
  let qTimer = null;
  $("q").addEventListener("input", (e) => {
    searchQ = e.target.value;
    clearTimeout(qTimer);
    qTimer = setTimeout(applyFilter, 150);   // debounce: don't scan on every keystroke
  });
  $("grpSeg").querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => {
      grp = b.dataset.g;
      $("grpSeg").querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      applyFilter();
    }));
  $("modeSeg").querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => setMode(b.dataset.m)));
  $("showDetails").addEventListener("change", (e) => $("panel").classList.toggle("show-details", e.target.checked));
  const clear = $("clearBtn");
  if (clear) clear.addEventListener("click", resetAll);
  const toExport = $("toExport");
  if (toExport) toExport.addEventListener("click", () =>
    showView(wizStep === "base" ? "export" : "base"));
}

// wire the Yes/No toggles for the currently rendered rows
function wireRows() {
  // collapse / expand a cluster group
  const toggleCluster = (h) => {
    const key = h.dataset.key;
    if (collapsed.has(key)) collapsed.delete(key); else collapsed.add(key);
    applyFilter();
  };
  $("tb").querySelectorAll(".rv-clhead").forEach((h) => {
    h.addEventListener("click", () => toggleCluster(h));
    h.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleCluster(h); }
    });
  });
  $("tb").querySelectorAll(".rv-yn").forEach((yn) => {
    const k = yn.dataset.k;             // "tab|code"
    const code = yn.dataset.code;       // bare code (for claim regex / child match)
    const btns = [...yn.querySelectorAll("button")];
    btns.forEach((b) => b.addEventListener("click", () => {
      answers[k] = b.dataset.a;
      touched.add(k);
      btns.forEach((x) => x.classList.toggle("act", x === b));
      const row = yn.closest(".rv-qrow");
      row.classList.toggle("changed", isChanged(payload.items[+row.dataset.i]));
      // Un-claiming a parent (gateway X.C -> No, or a feature -> No) withdraws
      // everything revealed under it, ON THE SAME endpoint.
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
      if (FEATURE_RE.test(code) || GATEWAY_RE.test(code) || code.startsWith("MCORE.")) scheduleGenerate();
      else applyFilter();
    }));
  });
  recount();
}

// optional-cluster row label: cluster display name, disambiguated by side for
// X.C. "Optional" itself is NOT part of the name -- the row carries an
// explicit Optional badge (rv-optcl), so the name stays clean for search
// and for the dialog title.
function chipLabel(it) {
  let name = (it.cluster || it.code).replace(/\s+Cluster$/i, "");
  if (it.code.endsWith(".C")) name += " (client)";
  return name;
}

// wire the optional-cluster catalog chips: a chip IS the cluster's gateway
// answer -- toggling it claims/withdraws the side and regenerates, exactly
// like the old gateway row's Yes/No.
function wireCatalog() {
  $("tb").querySelectorAll(".oc-chip").forEach((b) => b.addEventListener("click", () => {
    const k = b.dataset.k, code = b.dataset.code;
    const on = b.getAttribute("aria-pressed") === "true";
    answers[k] = on ? "no" : "yes";
    touched.add(k);
    b.setAttribute("aria-pressed", String(!on));
    if (answers[k] === "no") {
      const [t] = splitKey(k);
      payload.items.forEach((it) => {
        if (it.tab === t && (it.parent === code || it.code.startsWith(code + "."))) {
          const ck = keyOf(it);
          touched.delete(ck);
          answers[ck] = it.answer;
        }
      });
    }
    recount();
    saveSession();
    scheduleGenerate();
  }));
}

// Nested gateway model: a child item is only shown while its parent is Yes.
// Parent lookup is scoped to the item's own endpoint tab.
function isApplicable(it) {
  if (!it.parent) return true;
  if (answers[keyOf(it)] === "yes") return true;
  return answers[`${it.tab}|${it.parent}`] === "yes";
}

function applyFilter() {
  if (mode === "simple") { applySimpleFilter(); return; }
  const q = searchQ.toLowerCase();
  const scopeHits = {};   // "tab|group" -> hits (from data; only active rows in DOM)
  const matches = (it) => isApplicable(it)
    && (!q || it.code.toLowerCase().includes(q) || (it.question || it.code).toLowerCase().includes(q));
  payload.items.forEach((it) => {
    if (matches(it)) scopeHits[`${it.tab}|${it.group}`] = (scopeHits[`${it.tab}|${it.group}`] || 0) + 1;
  });

  // the optional-cluster catalog belongs to the Optional (manual) view only
  const cat = $("tb").querySelector(".rv-optcat");
  if (cat) cat.style.display = grp === "manual" ? "" : "none";

  // A search overrides collapse so matches are never hidden behind a folded cluster.
  const isCollapsed = (key) => collapsed.has(key) && !q;
  const clusterMatch = {};   // rows matching filter (regardless of collapse)
  let visible = 0;
  $("tb").querySelectorAll(".rv-qrow").forEach((row) => {
    const it = payload.items[+row.dataset.i];
    const m = it.group === grp && matches(it);
    const key = row.dataset.key;
    if (m) { visible++; clusterMatch[key] = (clusterMatch[key] || 0) + 1; }
    row.style.display = (m && !isCollapsed(key)) ? "" : "none";
  });
  $("tb").querySelectorAll(".rv-clhead").forEach((h) => {
    const key = h.dataset.key;
    const n = clusterMatch[key] || 0;
    h.style.display = n ? "" : "none";                 // header stays visible when folded
    h.classList.toggle("collapsed", isCollapsed(key));
    h.setAttribute("aria-expanded", String(!isCollapsed(key)));
    const cc = h.querySelector(".cc");
    if (cc) cc.textContent = n;
  });

  const counts = { decided: 0, manual: 0 };
  payload.items.forEach((it) => { if (it.tab === tab) counts[it.group]++; });
  const gset = (id, v) => { const e = $(id); if (e) e.textContent = `(${v})`; };
  gset("gc-decided", counts.decided); gset("gc-manual", counts.manual);

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
        `<button class="linklike" data-goto="${esc(t.id)}" data-g="${g}">${esc(t.label)} › ${g === "manual" ? "Optional" : "Mandatory"} (${n})</button>`).join(" · ")
    : "Nothing matches.";
  hint.hidden = false;
  hint.querySelectorAll("[data-goto]").forEach((b) =>
    b.addEventListener("click", () => switchTo(b.dataset.goto, b.dataset.g)));
}

function switchTo(tabId, group) {
  tab = tabId;
  grp = group;
  $("grpSeg").querySelectorAll("button").forEach((x) =>
    x.setAttribute("aria-pressed", String(x.dataset.g === group)));
  // a base match jumps to the Device-questions stage, an endpoint match back
  // to the design stage; showView -> syncStage re-renders with the new tab
  const targetStep = tabId === "base" ? "base" : "review";
  if (targetStep !== wizStep) showView(targetStep);
  else syncStage();
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
        saveSession();
        populateExport();   // refresh the recap; stay on the Export screen
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

// Plain-language spec-check dialog: lead with the item's name + why; PICS codes
// live under "Technical details". Resolves true = enable & continue, false =
// export as-is, null = cancel.
function confirmProblems(problems, warns = []) {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    const items = problems.slice(0, 20).map((p) => `
        <div class="rv-vitem"><div class="vic">!</div><div>
          <div class="vt">${esc(p.name || p.question || p.code)}${p.cluster ? ` <span class="cl">· ${esc(p.cluster)}</span>` : ""}</div>
          <div class="vw">${esc(p.why || "")}</div>
        </div></div>`).join("");
    const tech = problems.map((p) => `${esc(p.code)}${p.tab ? ` · EP ${esc(p.tab)}` : ""}`).join("<br>");
    const benign = warns.length ? `
        <div class="rv-benign"><b>${warns.length} expected notice${warns.length > 1 ? "s" : ""}</b>
          (no action needed): ${warns.map((w) => esc(w.name || w.code)).join(", ")}.
          The official CSA tool shows the same.</div>` : "";
    overlay.innerHTML = `
      <div class="modal" role="alertdialog" aria-label="Spec check">
        <h3>A few items are required by your selections</h3>
        <p style="color:var(--text-dim);font-size:13px;margin:0 0 14px">
          To keep the PICS spec‑compliant, these need to be <b>Yes</b>. Enable them
          automatically, or export as‑is.</p>
        ${items}
        ${problems.length > 20 ? `<p style="color:var(--text-dim);font-size:12.5px;margin:10px 0 0">…and ${problems.length - 20} more.</p>` : ""}
        <details class="rv-tech"><summary>Technical details (PICS codes)</summary>
          <div class="tb">${tech}</div></details>
        ${benign}
        <div class="modal-actions">
          <button class="btn" data-act="fix">Enable them &amp; export</button>
          <button class="btn ghost" data-act="asis">Export as‑is</button>
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
wireChips("flow", true);
wireChips("netcaps", false);
wireChips("ota", true);
wireChips("role", true);
// results update automatically on any form change — no Generate button
wireChips("primary", true);
["transport", "onboarding", "commdisc", "flow", "netcaps", "ota", "role"].forEach((id) =>
  $(id).addEventListener("click", (e) => {
    if (e.target.closest(".opt")) {
      updateCodeLabel();
      if (id === "transport") refreshPrimary();   // primary picker follows
      markDirty();
    }
  }));
$("primary").addEventListener("click", (e) => {
  if (e.target.closest(".opt")) { updatePrimaryHint(); markDirty(); }
});
refreshPrimary();   // boot: reflect the default transport selection
updateCodeLabel();  // boot: label reflects the default flow even with no session
$("addEndpoint").addEventListener("click", () => { addEndpointRow(); markDirty(); });
$("generateBtn").addEventListener("click", () => generate(null, true));
$("exportBtn").addEventListener("click", exportPICS);
$("downloadCode").addEventListener("click", downloadScaffold);
$("copyCode").addEventListener("click", copyScaffold);
$("genCode").addEventListener("change", renderScaffold);
$("backToReview").addEventListener("click", () => showView("base"));

// stepper switches between the three screens; Review/Export need a generated payload.
document.querySelectorAll("#stepper .rv-step").forEach((b) =>
  b.addEventListener("click", () => {
    const step = b.dataset.step;
    if (step !== "describe" && !payload) return;   // gated until Generate
    showView(step);
  }));

init().catch((err) => {
  $("initStatus").textContent = "Failed to initialize: " + (err.message || err);
  console.error(err);
});
