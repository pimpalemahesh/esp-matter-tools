"""
In-browser glue for esp-matter-mfg-tool running under Pyodide.

This module is loaded into the Pyodide runtime by app.js. It:
  * shims hashlib.pbkdf2_hmac (Pyodide's CPython is built without the OpenSSL
    _hashlib backend, so pbkdf2_hmac is missing),
  * exposes run_mfg_tool(config, files) which the JavaScript front-end calls.

It drives the *published* esp-matter-mfg-tool package (installed from PyPI by
app.js); it never imports anything from the source checkout.
"""

import base64
import copy
import csv
import hashlib
import hmac
import io
import logging
import os
import shutil
import struct
import traceback
import zipfile
from types import SimpleNamespace


# --- Shim: hashlib.pbkdf2_hmac (absent in Pyodide, used by deps/spake2p.py) ---
if not hasattr(hashlib, "pbkdf2_hmac"):
    def _pbkdf2_hmac(hash_name, password, salt, iterations, dklen=None):
        size = hmac.new(password, None, hash_name).digest_size
        dklen = dklen or size
        out = b""
        block = 1
        while len(out) < dklen:
            prev = hmac.new(password, salt + struct.pack(">I", block), hash_name).digest()
            acc = bytearray(prev)
            for _ in range(iterations - 1):
                prev = hmac.new(password, prev, hash_name).digest()
                for i in range(size):
                    acc[i] ^= prev[i]
            out += bytes(acc)
            block += 1
        return bytes(out[:dklen])

    hashlib.pbkdf2_hmac = _pbkdf2_hmac


WORK_DIR = "/work"
OUT_DIR = os.path.join(WORK_DIR, "out")
IN_DIR = os.path.join(WORK_DIR, "inputs")

# Every argument main_internal() expects, with CLI defaults. The UI overrides a
# subset; anything it leaves out keeps these defaults.
DEFAULTS = dict(
    count=1, target="esp32", size=0x6000, encrypt=False, log_level="info",
    outdir=OUT_DIR, generate_bin=True, no_secure_cert_bin=False,
    passcode=None, discriminator=None, commissioning_flow=0, discovery_mode=2,
    enable_dynamic_passcode=False, salt=None, verifier=None, iteration_count=10000,
    commissionable_data_in_secure_cert=False, dac_in_secure_cert=False,
    lifetime=36500, valid_from=None, cn_prefix="ESP32", cert=None, key=None,
    cert_dclrn=None, dac_cert=None, dac_key=None, ds_peripheral=False,
    efuse_key_id=-1, port=None, priv_key_pass=None, paa=False, pai=False,
    vendor_id=None, vendor_name=None, product_id=None, product_name=None,
    hw_ver=None, hw_ver_str=None, mfg_date=None, serial_num=None,
    enable_rotating_device_id=False, rd_id_uid=None, product_finish=None,
    rd_id_uid_in_secure_cert=False, product_color=None, part_number=None,
    calendar_types=None, locales=None, fixed_labels=None, supported_modes=None,
    product_label=None, product_url=None, csv=None, mcsv=None,
)

# Fields parsed with int(x, 0) so the UI can accept hex (0xFFF1) or decimal.
_INT_FIELDS = {
    "count", "size", "passcode", "discriminator", "commissioning_flow",
    "discovery_mode", "iteration_count", "lifetime", "efuse_key_id",
    "vendor_id", "product_id", "hw_ver",
}
# Space/comma separated multi-value fields.
_LIST_FIELDS = {"calendar_types", "locales", "fixed_labels", "supported_modes"}


def _coerce(key, value):
    if value is None or value == "":
        return None
    if key in _INT_FIELDS:
        return int(str(value), 0)
    if key in _LIST_FIELDS:
        parts = [p for p in str(value).replace(",", " ").split() if p]
        return parts or None
    return value


def _build_args(config):
    args = dict(DEFAULTS)
    for key, value in config.items():
        if key not in DEFAULTS:
            continue
        if isinstance(value, bool):
            args[key] = value
        else:
            coerced = _coerce(key, value)
            if coerced is not None:
                args[key] = coerced
    args["outdir"] = OUT_DIR
    return SimpleNamespace(**args)


def _write_inputs(files):
    """files: dict of {filename: Uint8Array/bytes}. Returns {filename: abspath}."""
    os.makedirs(IN_DIR, exist_ok=True)
    paths = {}
    for name, data in files.items():
        if hasattr(data, "to_py"):
            data = data.to_py()
        data = bytes(data)
        path = os.path.join(IN_DIR, name)
        with open(path, "wb") as fh:
            fh.write(data)
        paths[name] = path
    return paths


_PRISTINE_NVS_MAP = None


def _reset_tool_state():
    """Reset the tool's module-level globals between runs.

    The published tool keeps run state in module globals — fine for a one-shot
    CLI process, but stale across repeated calls in the same long-lived Pyodide
    session. Without this, a second generation inherits the first run's state
    (e.g. leftover NVS keys) and is corrupted. Clear them so each run is clean.
    """
    import sources.mfg_tool as mt
    mt.UUIDs.clear()
    mt.SECURE_CERT_INFO.clear()
    for store in (mt.PAI, mt.OUT_DIR, mt.OUT_FILE):
        for key in list(store):
            store[key] = None

    # chip_nvs.CHIP_NVS_MAP is mutated in place (keys appended, values set) on
    # every run. mfg_tool imports chip_nvs as a top-level module via the sources
    # sys.path shim, so reset whichever instance(s) are actually loaded. Snapshot
    # its pristine state on first use, restore it on later runs.
    global _PRISTINE_NVS_MAP
    import sys
    for modname in ("chip_nvs", "sources.chip_nvs"):
        cn = sys.modules.get(modname)
        if cn is None or not hasattr(cn, "CHIP_NVS_MAP"):
            continue
        if _PRISTINE_NVS_MAP is None:
            _PRISTINE_NVS_MAP = copy.deepcopy(cn.CHIP_NVS_MAP)
        cn.CHIP_NVS_MAP.clear()
        cn.CHIP_NVS_MAP.update(copy.deepcopy(_PRISTINE_NVS_MAP))


def _reset_dirs():
    for d in (OUT_DIR, IN_DIR):
        shutil.rmtree(d, ignore_errors=True)
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(IN_DIR, exist_ok=True)
    # esp_secure_cert generation creates ./esp_secure_cert_data relative to cwd
    shutil.rmtree(os.path.join(os.getcwd(), "esp_secure_cert_data"), ignore_errors=True)


class _ListHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(self.format(record))


def _collect_devices():
    """Parse per-device onboarding CSVs and QR PNGs for inline display."""
    devices = []
    for root, _dirs, files in os.walk(OUT_DIR):
        for fname in sorted(files):
            if not fname.endswith("-onb_codes.csv"):
                continue
            uuid = fname[: -len("-onb_codes.csv")]
            dev = {"uuid": uuid}
            with open(os.path.join(root, fname)) as fh:
                rows = list(csv.DictReader(fh))
            if rows:
                dev.update({
                    "qrcode": rows[0].get("qrcode", ""),
                    "manualcode": rows[0].get("manualcode", "").strip('"'),
                    "discriminator": rows[0].get("discriminator", ""),
                    "passcode": rows[0].get("passcode", ""),
                })
            png_path = os.path.join(root, f"{uuid}-qrcode.png")
            if os.path.exists(png_path):
                with open(png_path, "rb") as fh:
                    dev["qrcode_png_b64"] = base64.b64encode(fh.read()).decode()
            devices.append(dev)
    return devices


def _zip_outputs():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(OUT_DIR):
            for fname in files:
                full = os.path.join(root, fname)
                arc = os.path.relpath(full, OUT_DIR)
                zf.write(full, arc)
    return base64.b64encode(buf.getvalue()).decode()


def _read_summary():
    for root, _dirs, files in os.walk(OUT_DIR):
        for fname in files:
            if fname.startswith("summary-") and fname.endswith(".csv"):
                with open(os.path.join(root, fname)) as fh:
                    return fh.read()
    return ""


def run_mfg_tool(config, files=None):
    """Entry point called from JavaScript.

    config : plain object of CLI-equivalent options (keys match arg names).
    files  : optional object of {filename: bytes} for uploaded cert/csv inputs.
    Returns a JSON-serialisable dict.
    """
    if hasattr(config, "to_py"):
        config = config.to_py()
    config = dict(config)
    if files is not None and hasattr(files, "to_py"):
        files = files.to_py()
    files = dict(files or {})

    handler = _ListHandler()
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)

    try:
        _reset_dirs()
        paths = _write_inputs(files)
        # Map any uploaded-file option values to their on-FS paths.
        for opt in ("cert", "key", "dac_cert", "dac_key", "cert_dclrn", "csv", "mcsv"):
            val = config.get(opt)
            if val and val in paths:
                config[opt] = paths[val]

        args = _build_args(config)
        if args.vendor_id is None or args.product_id is None:
            return {
                "ok": False,
                "error": "Vendor ID and Product ID are required.",
                "log": "",
            }

        # Import the published package lazily so import errors surface as logs.
        import sources  # noqa: F401  (runs sys.path shim in __init__)
        from sources.mfg_tool import main_internal

        _reset_tool_state()
        main_internal(args)

        return {
            "ok": True,
            "log": "\n".join(handler.records),
            "devices": _collect_devices(),
            "summary_csv": _read_summary(),
            "zip_b64": _zip_outputs(),
        }
    except SystemExit as exc:
        return {
            "ok": False,
            "error": f"Tool exited (code {exc.code}). Check the inputs and log below.",
            "log": "\n".join(handler.records),
        }
    except BaseException as exc:  # noqa: BLE001  surface everything to the UI
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "log": "\n".join(handler.records) + "\n\n" + traceback.format_exc(),
        }
    finally:
        root_logger.removeHandler(handler)
