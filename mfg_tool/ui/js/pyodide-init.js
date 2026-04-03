import { PYODIDE_INDEX_URL, MFG_PYTHON_RUNTIME } from './config.js';

export async function fetchMfgPythonRuntimeSource() {
  const url = new URL(MFG_PYTHON_RUNTIME, window.location.href);
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to load ${url.href} (${res.status})`);
  }
  return res.text();
}

/**
 * @param {object} deps
 * @param {(msg: string, type?: string) => void} deps.log
 * @param {() => void} deps.clearLog
 * @param {(text: string, state?: string) => void} deps.setStatus
 * @param {(percent: number) => void} deps.updateProgress
 * @param {() => HTMLButtonElement} deps.getGenerateButton
 */
export async function bootstrapPyodide(deps) {
  const { log, clearLog, setStatus, updateProgress, getGenerateButton } = deps;

  clearLog();
  log('Starting Pyodide initialization...', 'info');
  setStatus('Loading Pyodide runtime...', 'loading');
  updateProgress(10);

  const pyodide = await loadPyodide({ indexURL: PYODIDE_INDEX_URL });
  log('Pyodide runtime loaded', 'success');
  updateProgress(30);

  setStatus('Installing Python packages...', 'loading');
  await pyodide.loadPackage(['micropip']);
  updateProgress(40);

  const micropip = pyodide.pyimport('micropip');
  log('Installing cryptography...', 'info');
  await micropip.install(['cryptography']);
  updateProgress(55);

  log('Installing ecdsa...', 'info');
  await micropip.install(['ecdsa']);
  updateProgress(70);

  log('Installing esp-idf-nvs-partition-gen...', 'info');
  await micropip.install(['esp-idf-nvs-partition-gen']);
  updateProgress(85);

  setStatus('Loading MFG tool modules...', 'loading');
  const pythonSrc = await fetchMfgPythonRuntimeSource();
  await pyodide.runPythonAsync(pythonSrc);
  updateProgress(100);

  setStatus('Ready to generate', 'ready');
  getGenerateButton().disabled = false;
  log('All modules loaded successfully!', 'success');
  log('Ready to generate factory partition data.', 'success');

  return pyodide;
}
