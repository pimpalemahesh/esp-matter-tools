//!/usr/bin/env python3

// Copyright 2026 Espressif Systems (Shanghai) PTE LTD
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

const PYODIDE_VERSION = "0.28.3";
const PYODIDE_CDN = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;
// Unpinned: always install the latest published release.
const MFG_TOOL_SPEC = "esp-matter-mfg-tool";

// WASM-native wheels bundled with Pyodide.
const NATIVE_PACKAGES = ["micropip", "cryptography", "cffi", "bitarray"];

// Dependencies are installed here (not resolved from the package) because it is
// installed with deps=False — its pins have no WASM wheels. Keep this list in
// sync with the latest esp-matter-mfg-tool's requirements.
// python-stdnum 1.18 avoids a top-level `import ssl`, which Pyodide lacks.
const PYPI_PURE_DEPS = [
  "ecdsa", "pypng", "python-stdnum==1.18", "click",
  "click-option-group", "construct", "esp-idf-nvs-partition-gen",
];

// Deps that publish sdists only (micropip can't build sdists); served as
// pre-built wheels. Lowercase names match prepare_assets.sh output.
const VENDORED_WHEELS = [
  "wheels/pyqrcode-1.2.1-py3-none-any.whl",
  "wheels/esp_secure_cert_tool-2.3.6-py3-none-any.whl",
];

let pyodide = null;
let ready = false;

const $ = (id) => document.getElementById(id);

function setStatus(msg, kind = "info") {
  const el = $("status");
  el.textContent = msg;
  el.className = `status ${kind}`;
}

function logBoot(msg) {
  const el = $("boot-log");
  el.textContent += msg + "\n";
  el.scrollTop = el.scrollHeight;
}

function populateChoices(choices) {
  for (const [opt, names] of Object.entries(choices)) {
    const sel = document.querySelector(`select[data-opt="${opt}"]`);
    if (!sel) continue;
    sel.innerHTML = sel.multiple ? "" : '<option value="">— not set —</option>';
    for (const name of names) {
      const o = document.createElement("option");
      o.value = name;
      o.textContent = name;
      sel.appendChild(o);
    }
  }
}

function setGenerateState(state) {
  const btn = $("generate-btn");
  const label = $("generate-label");
  btn.classList.toggle("is-busy", state === "loading" || state === "busy");
  btn.disabled = state !== "ready";
  label.textContent = {
    loading: "Preparing runtime…",
    ready: "Generate",
    busy: "Generating…",
    failed: "Runtime unavailable",
  }[state];
}

async function loadPyodideScript() {
  await new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = PYODIDE_CDN + "pyodide.js";
    s.onload = resolve;
    s.onerror = () => reject(new Error("Failed to load Pyodide from CDN"));
    document.head.appendChild(s);
  });
}

async function micropipInstall(specs, deps) {
  pyodide.globals.set("SPECS", pyodide.toPy(specs));
  await pyodide.runPythonAsync(
    `import micropip\nawait micropip.install([str(s) for s in SPECS], deps=${deps ? "True" : "False"})`
  );
}

async function initRuntime() {
  setStatus("Loading Python runtime (Pyodide)…", "busy");
  logBoot("Loading Pyodide " + PYODIDE_VERSION);
  await loadPyodideScript();
  pyodide = await loadPyodide({ indexURL: PYODIDE_CDN });

  setStatus("Loading native packages…", "busy");
  logBoot("loadPackage: " + NATIVE_PACKAGES.join(", "));
  await pyodide.loadPackage(NATIVE_PACKAGES);

  setStatus("Installing dependencies from PyPI…", "busy");
  logBoot("micropip: " + PYPI_PURE_DEPS.join(", "));
  await micropipInstall(PYPI_PURE_DEPS, true);

  setStatus("Installing vendored wheels…", "busy");
  logBoot("micropip: vendored wheels");
  await micropipInstall(VENDORED_WHEELS, false);

  // deps=False: the published package pins versions with no WASM wheels
  // (e.g. cryptography==44.0.1); deps are satisfied above.
  setStatus("Installing esp-matter-mfg-tool from PyPI…", "busy");
  logBoot("micropip: " + MFG_TOOL_SPEC);
  await micropipInstall([MFG_TOOL_SPEC], false);

  logBoot("Loading mfg_runner.py");
  await pyodide.runPythonAsync(await (await fetch("mfg_runner.py")).text());

  const choices = JSON.parse(
    await pyodide.runPythonAsync("import json; json.dumps(get_choices())")
  );
  populateChoices(choices);

  ready = true;
  setStatus("Ready — fill in the form and generate.", "ok");
  logBoot("Ready.");
  setGenerateState("ready");
}

const BUNDLED_CERTS = {
  "test-paa": {
    paa: true,
    files: [
      ["test_certs/paa_cert.pem", "cert"],
      ["test_certs/paa_key.pem", "key"],
    ],
  },
  "test-pai": {
    pai: true,
    files: [
      ["test_certs/pai_cert.pem", "cert"],
      ["test_certs/pai_key.pem", "key"],
      ["test_certs/cd.der", "cert_dclrn"],
    ],
  },
};

const CUSTOM_CERT_INPUTS = {
  "f-cert": "cert",
  "f-key": "key",
  "f-dac-cert": "dac_cert",
  "f-dac-key": "dac_key",
  "f-cert-dclrn": "cert_dclrn",
};
const EXTRA_INPUTS = { "f-csv": "csv", "f-mcsv": "mcsv" };

function readForm() {
  const config = {};
  document.querySelectorAll("[data-opt]").forEach((el) => {
    const opt = el.dataset.opt;
    if (el.type === "checkbox") {
      config[opt] = el.checked;
    } else if (el.multiple) {
      const vals = [...el.selectedOptions].map((o) => o.value);
      if (vals.length) config[opt] = vals.join(" ");
    } else if (el.value !== "") {
      config[opt] = el.value;
    }
  });
  return config;
}

async function fetchBytes(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`Could not load ${url} (${r.status})`);
  return new Uint8Array(await r.arrayBuffer());
}

async function addUpload(inputId, opt, config, files) {
  const input = $(inputId);
  if (input && input.files.length > 0) {
    const file = input.files[0];
    files[file.name] = new Uint8Array(await file.arrayBuffer());
    config[opt] = file.name;
    return true;
  }
  return false;
}

async function gatherCertsAndFiles(config) {
  const files = {};
  const mode = $("cert-mode").value;
  config.paa = false;
  config.pai = false;

  if (mode === "none") {
  } else if (mode === "custom") {
    config[$("custom-cert-kind").value] = true;
    for (const [id, opt] of Object.entries(CUSTOM_CERT_INPUTS)) {
      await addUpload(id, opt, config, files);
    }
  } else {
    const spec = BUNDLED_CERTS[mode];
    config.paa = !!spec.paa;
    config.pai = !!spec.pai;
    for (const [url, opt] of spec.files) {
      const name = url.split("/").pop();
      files[name] = await fetchBytes(url);
      config[opt] = name;
    }
  }

  for (const [id, opt] of Object.entries(EXTRA_INPUTS)) {
    await addUpload(id, opt, config, files);
  }
  return files;
}

function downloadZip(b64, filename) {
  const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  const blob = new Blob([bytes], { type: "application/zip" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function renderResult(result, vid, pid) {
  const out = $("results");
  out.innerHTML = "";

  if (!result.ok) {
    out.innerHTML = `<div class="error-box"><strong>Generation failed:</strong> ${escapeHtml(
      result.error || "unknown error"
    )}</div>`;
    $("run-log").textContent = result.log || "";
    return;
  }

  const header = document.createElement("div");
  header.className = "result-header";
  const dlName = `matter_mfg_${vid || "out"}_${pid || ""}.zip`;
  header.innerHTML = `<span>✅ Generated ${result.devices.length} device(s).</span>`;
  const dlBtn = document.createElement("button");
  dlBtn.innerHTML = '<i class="fas fa-download"></i> Download all (.zip)';
  dlBtn.className = "btn btn-primary";
  dlBtn.onclick = () => downloadZip(result.zip_b64, dlName);
  header.appendChild(dlBtn);
  out.appendChild(header);

  const canFlash = window.MfgFlasher && MfgFlasher.isSupported();
  if (canFlash) out.appendChild(buildFlashPanel());

  const grid = document.createElement("div");
  grid.className = "device-grid";
  for (const dev of result.devices) {
    const card = document.createElement("div");
    card.className = "device-card";
    const img = dev.qrcode_png_b64
      ? `<img alt="QR code" src="data:image/png;base64,${dev.qrcode_png_b64}">`
      : "<div class='no-qr'>(no QR — dynamic passcode)</div>";
    card.innerHTML = `
      ${img}
      <div class="dev-meta">
        <div><span>Passcode</span><code>${escapeHtml(dev.passcode || "—")}</code></div>
        <div><span>Discriminator</span><code>${escapeHtml(dev.discriminator || "—")}</code></div>
        <div><span>Manual</span><code>${escapeHtml(dev.manualcode || "—")}</code></div>
        <div class="uuid"><span>UUID</span><code>${escapeHtml(dev.uuid)}</code></div>
      </div>`;
    if (canFlash && dev.partition_b64) card.appendChild(buildFlashControls(dev));
    grid.appendChild(card);
  }
  out.appendChild(grid);

  $("run-log").textContent = result.log || "";
}

function buildFlashPanel() {
  const panel = document.createElement("div");
  panel.className = "flash-panel";
  panel.innerHTML = `
    <div class="flash-row">
      <label>Flash offset
        <input id="flash-offset" class="form-control" type="text" value="0x10000" />
      </label>
      <label>Auto-fill from partition table (CSV or .bin)
        <input id="flash-ptable" class="form-control" type="file" accept=".csv,.bin" />
      </label>
      <label class="flash-ptable-pick" style="display:none">Partition
        <select id="flash-ptable-sel" class="form-control"></select>
      </label>
    </div>
    <p class="hint">Flashes the generated partition to an ESP over USB (Chrome/Edge), then resets
      it to run. The offset must match your partition table; this writes only the partition, not
      the app. If connecting fails, unplug and replug the board, then try again.</p>`;
  panel.querySelector("#flash-ptable").addEventListener("change", onPartitionTable);
  panel.querySelector("#flash-ptable-sel").addEventListener("change", (e) => {
    $("flash-offset").value = e.target.value;
  });
  return panel;
}

async function onPartitionTable(evt) {
  const file = evt.target.files[0];
  if (!file) return;
  const bytes = new Uint8Array(await file.arrayBuffer());
  const parts = MfgFlasher.parsePartitionTable(file.name, bytes);
  const sel = $("flash-ptable-sel");
  if (!parts.length) {
    sel.parentElement.style.display = "none";
    return;
  }
  sel.innerHTML = parts
    .map((p) => `<option value="0x${p.offset.toString(16)}">${escapeHtml(p.name)} (${escapeHtml(p.subtype)}) @ 0x${p.offset.toString(16)}</option>`)
    .join("");
  sel.parentElement.style.display = "";
  const nvs = parts.find((p) => p.subtype === "nvs" || p.subtype === "1");
  const pick = nvs || parts[0];
  sel.value = "0x" + pick.offset.toString(16);
  $("flash-offset").value = sel.value;
}

function buildFlashControls(dev) {
  const wrap = document.createElement("div");
  wrap.className = "flash-controls";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "btn btn-secondary btn-flash";
  btn.innerHTML = '<i class="fas fa-bolt"></i> Flash to device';
  const bar = document.createElement("div");
  bar.className = "flash-progress";
  bar.innerHTML = '<span></span>';
  btn.onclick = () => flashOne(dev, btn, bar);
  wrap.append(btn, bar);
  return wrap;
}

async function flashOne(dev, btn, bar) {
  const offset = parseInt($("flash-offset").value, 0);
  if (Number.isNaN(offset)) {
    setStatus("Enter a valid flash offset (e.g. 0x10000).", "error");
    return;
  }
  const fill = bar.firstElementChild;
  btn.disabled = true;
  btn.classList.add("is-busy");
  setStatus("Flashing — select the serial port…", "busy");
  try {
    await MfgFlasher.flashDevice(dev.partition_b64, offset, {
      onLog: appendRunLog,
      onProgress: (f) => { fill.style.width = Math.round(f * 100) + "%"; },
    });
    fill.style.width = "100%";
    setStatus("Flashed " + dev.uuid.slice(0, 8) + " at 0x" + offset.toString(16) +
      " — device reset and running.", "ok");
  } catch (err) {
    setStatus("Flash failed: " + err.message, "error");
    appendRunLog("Flash error: " + (err.stack || err));
  } finally {
    btn.disabled = false;
    btn.classList.remove("is-busy");
  }
}

function appendRunLog(line) {
  const el = $("run-log");
  el.textContent += (el.textContent ? "\n" : "") + line;
  el.scrollTop = el.scrollHeight;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

async function onGenerate(evt) {
  evt.preventDefault();
  if (!ready) return;

  setGenerateState("busy");
  setStatus("Generating manufacturing partitions…", "busy");
  $("results").innerHTML = "";
  $("run-log").textContent = "";

  try {
    const config = readForm();
    const files = await gatherCertsAndFiles(config);

    pyodide.globals.set("JS_CONFIG", pyodide.toPy(config));
    pyodide.globals.set("JS_FILES", pyodide.toPy(files));

    const resultJson = await pyodide.runPythonAsync(`
import json
json.dumps(run_mfg_tool(JS_CONFIG, JS_FILES))
`);
    const result = JSON.parse(resultJson);
    renderResult(result, config.vendor_id, config.product_id);
    setStatus(result.ok ? "Done." : "Finished with errors — see log.", result.ok ? "ok" : "error");
  } catch (err) {
    setStatus("Error: " + err.message, "error");
    $("run-log").textContent = String(err.stack || err);
  } finally {
    setGenerateState("ready");
  }
}

const CERT_MODE_NOTES = {
  "test-paa": "Generates a PAI then per-device DACs from the bundled Matter test PAA. Works with any VID/PID.",
  "test-pai": "Generates per-device DACs from the bundled test PAI. Requires VID 0xFFF2 and PID 0x8001.",
  "none": "Only commissioning data (passcode, discriminator, QR) — no device attestation certificate.",
  "custom": "Upload your own PAA/PAI (and optionally a DAC) under Advanced options → Attestation.",
};

function wireCertMode() {
  const sel = $("cert-mode");
  const update = () => {
    $("cert-mode-note").textContent = CERT_MODE_NOTES[sel.value] || "";
  };
  sel.addEventListener("change", update);
  update();
}

window.addEventListener("DOMContentLoaded", () => {
  $("mfg-form").addEventListener("submit", onGenerate);
  wireCertMode();
  initRuntime().catch((err) => {
    setStatus("Failed to initialise: " + err.message, "error");
    logBoot("FATAL: " + (err.stack || err));
    setGenerateState("failed");
  });
});
