import { bootstrapPyodide } from './pyodide-init.js';
import { mapToObject, decodeContent } from './results.js';

let pyodide = null;
const generatedFiles = {};
let paiCertContent = null;
let paiKeyContent = null;
let paaCertContent = null;
let paaKeyContent = null;
let cdContent = null;
let certMode = 'pai';

const statusIndicator = document.getElementById('statusIndicator');
const statusText = document.getElementById('statusText');
const progressFill = document.getElementById('progressFill');
const generateBtn = document.getElementById('generateBtn');
const outputArea = document.getElementById('outputArea');
const filesCard = document.getElementById('filesCard');
const filesList = document.getElementById('filesList');
const summaryCard = document.getElementById('summaryCard');
const deviceSummaries = document.getElementById('deviceSummaries');

function log(msg, type = 'info') {
  const span = document.createElement('span');
  span.className = `log-${type}`;
  span.textContent = `[${new Date().toLocaleTimeString()}] ${msg}\n`;
  outputArea.appendChild(span);
  outputArea.scrollTop = outputArea.scrollHeight;
}

function clearLog() {
  outputArea.innerHTML = '';
}

function updateProgress(percent) {
  progressFill.style.width = `${percent}%`;
}

function setStatus(text, state = 'loading') {
  statusText.textContent = text;
  statusIndicator.className = 'status-indicator';
  if (state === 'ready') statusIndicator.classList.add('ready');
  else if (state === 'error') statusIndicator.classList.add('error');
}

function setupFileUpload(uploadId, inputId, nameId, callback) {
  const upload = document.getElementById(uploadId);
  const input = document.getElementById(inputId);
  const nameEl = document.getElementById(nameId);

  upload.addEventListener('click', () => input.click());
  input.addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (file) {
      const content = await file.text();
      callback(content, file.name);
      nameEl.textContent = file.name;
      upload.classList.add('has-file');
    }
  });
}

function getFormConfig() {
  const parseHex = (val) => {
    if (!val) return null;
    if (typeof val === 'string' && val.toLowerCase().startsWith('0x')) {
      return parseInt(val, 16);
    }
    return parseInt(val, 10);
  };

  const config = {
    vendor_id: parseHex(document.getElementById('vendorId').value) || 0xfff1,
    product_id: parseHex(document.getElementById('productId').value) || 0x8000,
    count: parseInt(document.getElementById('deviceCount').value, 10) || 1,
    target: document.getElementById('targetChip').value,
    vendor_name: document.getElementById('vendorName').value || '',
    product_name: document.getElementById('productName').value || '',
    commissioning_flow: parseInt(document.getElementById('commissioningFlow').value, 10),
    discovery_mode: parseInt(document.getElementById('discoveryMode').value, 10),
    cn_prefix: document.getElementById('cnPrefix').value || 'ESP32',
    size: parseHex(document.getElementById('partitionSize').value) || 0x6000,
    iteration_count: parseInt(document.getElementById('iterationCount').value, 10) || 10000,
    enable_dynamic_passcode: document.getElementById('enableDynamicPasscode').checked,
  };

  const passcode = document.getElementById('passcode').value;
  const discriminator = document.getElementById('discriminator').value;
  if (passcode) config.passcode = parseHex(passcode);
  if (discriminator) config.discriminator = parseHex(discriminator);

  return config;
}

function downloadFile(path) {
  const content = generatedFiles[path];
  let blob;

  if (content instanceof Uint8Array) {
    blob = new Blob([content], { type: 'application/octet-stream' });
  } else if (typeof content === 'string') {
    blob = new Blob([content], { type: 'text/plain' });
  } else {
    blob = new Blob([content], { type: 'application/octet-stream' });
  }

  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = path.split('/').pop();
  a.click();
  URL.revokeObjectURL(url);
}

function displayFiles() {
  filesCard.style.display = 'block';
  filesList.innerHTML = '';

  const sortedFiles = Object.keys(generatedFiles).sort();

  for (const path of sortedFiles) {
    const content = generatedFiles[path];
    const item = document.createElement('div');
    item.className = 'file-item';

    let icon = 'fa-file';

    if (path.endsWith('.bin')) {
      icon = 'fa-microchip';
      item.classList.add('binary');
    } else if (path.endsWith('.csv')) {
      icon = 'fa-file-csv';
    } else if (path.endsWith('.pem') || path.endsWith('.der')) {
      icon = 'fa-certificate';
      item.classList.add('cert');
    }

    const size =
      content instanceof Uint8Array ? content.length : new Blob([content]).size;
    const sizeStr = size > 1024 ? `${(size / 1024).toFixed(1)} KB` : `${size} B`;
    const displayPath =
      path.length > 50 ? `...${path.substring(path.length - 47)}` : path;

    const iconEl = document.createElement('i');
    iconEl.className = `fas ${icon}`;

    const nameEl = document.createElement('span');
    nameEl.className = 'name';
    nameEl.title = path;
    nameEl.textContent = displayPath;

    const sizeEl = document.createElement('span');
    sizeEl.className = 'size';
    sizeEl.textContent = sizeStr;

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn btn-secondary btn-sm';
    btn.innerHTML = '<i class="fas fa-download"></i>';
    btn.addEventListener('click', () => downloadFile(path));

    item.append(iconEl, nameEl, sizeEl, btn);
    filesList.appendChild(item);
  }
}

async function downloadAllAsZip() {
  const zip = new JSZip();

  for (const [path, content] of Object.entries(generatedFiles)) {
    zip.file(path, content);
  }

  const blob = await zip.generateAsync({ type: 'blob' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'esp_matter_mfg_data.zip';
  a.click();
  URL.revokeObjectURL(url);

  log('Downloaded all files as ZIP', 'success');
}

async function generatePartition() {
  const config = getFormConfig();

  clearLog();
  log('Starting factory data generation...', 'info');
  log(
    `Vendor ID: 0x${config.vendor_id.toString(16).toUpperCase()}, Product ID: 0x${config.product_id.toString(16).toUpperCase()}`,
    'info',
  );
  log(`Generating ${config.count} device(s)...`, 'info');

  generateBtn.disabled = true;
  Object.keys(generatedFiles).forEach((k) => delete generatedFiles[k]);
  deviceSummaries.innerHTML = '';

  try {
    pyodide.globals.set('js_config', pyodide.toPy(config));
    pyodide.globals.set('js_pai_cert', paiCertContent || '');
    pyodide.globals.set('js_pai_key', paiKeyContent || '');
    pyodide.globals.set('js_paa_cert', paaCertContent || '');
    pyodide.globals.set('js_paa_key', paaKeyContent || '');

    if (certMode === 'pai' && paiCertContent && paiKeyContent) {
      log('Using PAI certificate for DAC generation', 'info');
    } else if (certMode === 'paa' && paaCertContent && paaKeyContent) {
      log('Using PAA certificate - will generate PAI and DAC', 'info');
    } else {
      log('No certificates provided - generating commissioning data only', 'warning');
    }

    const result = await pyodide.runPythonAsync(`
config = dict(js_config)
pai_cert = js_pai_cert if js_pai_cert else None
pai_key = js_pai_key if js_pai_key else None
paa_cert = js_paa_cert if js_paa_cert else None
paa_key = js_paa_key if js_paa_key else None

result = generate_mfg_data(config, pai_cert, pai_key, paa_cert, paa_key)
result
`);

    const jsResult = result.toJs({ dict_converter: Object.fromEntries });

    if (jsResult.errors && jsResult.errors.length > 0) {
      jsResult.errors.forEach((err) => log(err, 'error'));
    }

    const vidPid = `${config.vendor_id.toString(16).padStart(4, '0')}_${config.product_id.toString(16).padStart(4, '0')}`;

    for (const [filename, content] of Object.entries(jsResult.staging || {})) {
      const path = `${vidPid}/staging/${filename}`;
      generatedFiles[path] = decodeContent(content);
      log(`Generated: staging/${filename}`, 'success');
    }

    for (const device of jsResult.devices) {
      const devicePath = `${vidPid}/${device.uuid}`;
      const filesObj = mapToObject(device.files) || {};

      for (const [filename, content] of Object.entries(filesObj)) {
        const fullPath = `${devicePath}/${filename}`;
        const decoded = decodeContent(content);
        generatedFiles[fullPath] = decoded;

        if (filename.endsWith('.bin')) {
          const size = decoded instanceof Uint8Array ? decoded.length : 'unknown';
          log(`  ${filename}: ${size} bytes`, 'info');
        }
      }

      const fileKeys = Object.keys(filesObj);
      const hasBin = fileKeys.some(
        (f) => f.endsWith('.bin') && f.includes('partition'),
      );
      const hasDac = fileKeys.some((f) => f.includes('DAC_cert'));

      let status = `Device ${device.index + 1}: ${device.uuid}`;
      if (hasDac) status += ' [DAC]';
      if (hasBin) status += ' [BIN]';
      log(status, 'success');

      const summaryDiv = document.createElement('div');
      summaryDiv.className = 'device-summary';
      summaryDiv.innerHTML = `
                        <h4>Device ${device.index + 1}: ${device.uuid.substring(0, 8)}...</h4>
                        <div class="codes">
                            <span><strong>QR:</strong> ${device.qr_payload}</span>
                            <span><strong>Manual:</strong> ${device.manual_code}</span>
                            <span><strong>Passcode:</strong> ${device.passcode} | <strong>Discriminator:</strong> ${device.discriminator}</span>
                        </div>
                    `;
      deviceSummaries.appendChild(summaryDiv);
    }

    if (jsResult.summary_filename) {
      generatedFiles[`${vidPid}/${jsResult.summary_filename}`] =
        jsResult.summary_content;
      log(`Generated: ${jsResult.summary_filename}`, 'success');
    }

    if (jsResult.cn_dacs_filename) {
      generatedFiles[`${vidPid}/${jsResult.cn_dacs_filename}`] =
        jsResult.cn_dacs_content;
      log(`Generated: ${jsResult.cn_dacs_filename}`, 'success');
    }

    log('', 'info');
    log(`Generation complete! ${jsResult.devices.length} device(s) generated.`, 'success');
    if (jsResult.has_certs) {
      log('Certificates and partition binaries included.', 'success');
    }

    displayFiles();
    summaryCard.style.display = 'block';
  } catch (error) {
    log(`Generation error: ${error.message}`, 'error');
    console.error(error);
  } finally {
    generateBtn.disabled = false;
  }
}

function resetForm() {
  document.getElementById('vendorId').value = '0xFFF1';
  document.getElementById('productId').value = '0x8000';
  document.getElementById('deviceCount').value = '1';
  document.getElementById('targetChip').selectedIndex = 0;
  document.getElementById('vendorName').value = '';
  document.getElementById('productName').value = '';
  document.getElementById('partitionSize').value = '0x6000';
  document.getElementById('cnPrefix').value = 'ESP32';
  document.getElementById('passcode').value = '';
  document.getElementById('discriminator').value = '';
  document.getElementById('commissioningFlow').selectedIndex = 0;
  document.getElementById('discoveryMode').selectedIndex = 0;
  document.getElementById('iterationCount').value = '10000';
  document.getElementById('enableDynamicPasscode').checked = false;

  paiCertContent = null;
  paiKeyContent = null;
  paaCertContent = null;
  paaKeyContent = null;
  cdContent = null;

  document.querySelectorAll('.file-upload').forEach((el) => {
    el.classList.remove('has-file');
  });
  document.querySelectorAll('.filename').forEach((el) => {
    el.textContent = '';
  });
  document.querySelectorAll('input[type="file"]').forEach((el) => {
    el.value = '';
  });

  clearLog();
  log('Form reset. Ready to generate.', 'info');
  filesCard.style.display = 'none';
  summaryCard.style.display = 'none';
  Object.keys(generatedFiles).forEach((k) => delete generatedFiles[k]);
  deviceSummaries.innerHTML = '';
}

function wireUi() {
  setupFileUpload('paiCertUpload', 'paiCertFile', 'paiCertName', (c) => {
    paiCertContent = c;
  });
  setupFileUpload('paiKeyUpload', 'paiKeyFile', 'paiKeyName', (c) => {
    paiKeyContent = c;
  });
  setupFileUpload('paaCertUpload', 'paaCertFile', 'paaCertName', (c) => {
    paaCertContent = c;
  });
  setupFileUpload('paaKeyUpload', 'paaKeyFile', 'paaKeyName', (c) => {
    paaKeyContent = c;
  });

  document.getElementById('cdUpload').addEventListener('click', () => {
    document.getElementById('cdFile').click();
  });
  document.getElementById('cdFile').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (file) {
      const buffer = await file.arrayBuffer();
      cdContent = new Uint8Array(buffer);
      document.getElementById('cdName').textContent = file.name;
      document.getElementById('cdUpload').classList.add('has-file');
    }
  });

  document.querySelectorAll('[data-cert-tab]').forEach((tab) => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('[data-cert-tab]').forEach((t) => {
        t.classList.remove('active');
      });
      tab.classList.add('active');
      certMode = tab.dataset.certTab;

      document.getElementById('paiTab').classList.toggle('hidden', certMode !== 'pai');
      document.getElementById('paaTab').classList.toggle('hidden', certMode !== 'paa');
      document.getElementById('noneTab').classList.toggle('hidden', certMode !== 'none');
    });
  });

  generateBtn.addEventListener('click', generatePartition);
  document.getElementById('resetBtn').addEventListener('click', resetForm);
  document.getElementById('downloadAllBtn').addEventListener('click', downloadAllAsZip);
}

async function main() {
  wireUi();

  try {
    pyodide = await bootstrapPyodide({
      log,
      clearLog,
      setStatus,
      updateProgress,
      getGenerateButton: () => generateBtn,
    });
  } catch (error) {
    setStatus(`Initialization failed: ${error.message}`, 'error');
    log(`Initialization error: ${error.message}`, 'error');
    console.error(error);
  }
}

main();
