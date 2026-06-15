// Browser front-end: loads Pyodide, installs esp-matter-mfg-tool from PyPI, and
// runs it entirely client-side. Nothing leaves the browser.

const PYODIDE_VERSION = "0.28.3";
const PYODIDE_CDN = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;
const MFG_TOOL_SPEC = "esp-matter-mfg-tool==1.0.23";

// WASM-native wheels bundled with Pyodide.
const NATIVE_PACKAGES = ["micropip", "cryptography", "cffi", "bitarray"];

// Pure-Python deps installed by name from PyPI. python-stdnum 1.18 avoids a
// top-level `import ssl`, which Pyodide lacks.
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

// Generate button states: "loading" | "ready" | "busy" | "failed".
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

  ready = true;
  setStatus("Ready — fill in the form and generate.", "ok");
  logBoot("Ready.");
  setGenerateState("ready");
}

// Bundled test credentials. PAA works with any VID/PID; PAI is fixed to
// FFF2/8001 and pairs with its Certificate Declaration.
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

// Cert-related uploads (used only in "custom" mode).
const CUSTOM_CERT_INPUTS = {
  "f-cert": "cert",
  "f-key": "key",
  "f-dac-cert": "dac_cert",
  "f-dac-key": "dac_key",
  "f-cert-dclrn": "cert_dclrn",
};
// Extra-NVS uploads (apply in every mode).
const EXTRA_INPUTS = { "f-csv": "csv", "f-mcsv": "mcsv" };

function readForm() {
  const config = {};
  document.querySelectorAll("[data-opt]").forEach((el) => {
    const opt = el.dataset.opt;
    if (el.type === "checkbox") {
      config[opt] = el.checked;
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
    config[opt] = file.name; // runner maps name -> on-FS path
    return true;
  }
  return false;
}

// Populate config + files for the selected attestation mode. Returns files map.
async function gatherCertsAndFiles(config) {
  const files = {};
  const mode = $("cert-mode").value;
  config.paa = false;
  config.pai = false;

  if (mode === "none") {
    // commissioning data only
  } else if (mode === "custom") {
    config[$("custom-cert-kind").value] = true; // paa or pai
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

  // Extra NVS uploads apply regardless of attestation mode.
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
    grid.appendChild(card);
  }
  out.appendChild(grid);

  $("run-log").textContent = result.log || "";
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

// Show a short note for the selected attestation mode.
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
