"""Tests for the browser UI glue (mfg_tool/ui/mfg_runner.py).

run_mfg_tool() is plain CPython, so we drive it directly (no Pyodide) with the
same (config, files) payloads app.js sends, covering the four DAC modes,
coercion, validation, and zipped output.
"""

import base64
import io
import sys
import zipfile
from pathlib import Path

import pytest

# mfg_runner lives in the (otherwise static) UI folder.
UI_DIR = Path(__file__).resolve().parent.parent / "ui"
sys.path.insert(0, str(UI_DIR))

# Needs the published package and pyqrcode importable (as in CI); skip otherwise.
pytest.importorskip("sources")
pytest.importorskip("pyqrcode")

import mfg_runner  # noqa: E402

TEST_DATA = Path(__file__).resolve().parent.parent / "test_data"

# How app.js names the bundled files (source fixture -> UI filename).
PAA_CERT = ("paa_cert.pem", "Chip-Test-PAA-NoVID-Cert.pem")
PAA_KEY = ("paa_key.pem", "Chip-Test-PAA-NoVID-Key.pem")
PAI_CERT = ("pai_cert.pem", "Chip-Test-PAI-FFF2-8001-Cert.pem")
PAI_KEY = ("pai_key.pem", "Chip-Test-PAI-FFF2-8001-Key.pem")
CD_DER = ("cd.der", "Chip-Test-CD-FFF2-8001.der")
DAC_CERT = ("DAC_cert.pem", "DAC_cert.pem")              # signed by FFF2/8001 PAI
DAC_KEY = ("DAC_key.pem", "DAC_key.pem")
DAC_FFF1_CERT = ("dac.pem", "DAC-FFF1-8000-Cert.pem")    # signed by a *different* PAI
DAC_FFF1_KEY = ("dac_key.pem", "DAC-FFF1-8000-Key.pem")


def _files(*pairs):
    """Build the {filename: bytes} map app.js would upload."""
    return {ui_name: (TEST_DATA / src).read_bytes() for ui_name, src in pairs}


@pytest.fixture(autouse=True)
def _isolated_work(tmp_path, monkeypatch):
    """Point the runner's in-memory-FS dirs at a temp dir and isolate cwd."""
    monkeypatch.setattr(mfg_runner, "OUT_DIR", str(tmp_path / "out"))
    monkeypatch.setattr(mfg_runner, "IN_DIR", str(tmp_path / "in"))
    monkeypatch.chdir(tmp_path)


def _zip_names(result):
    data = base64.b64decode(result["zip_b64"])
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return zf.namelist()


# --- validation / coercion -------------------------------------------------

def test_missing_vendor_id_is_rejected():
    res = mfg_runner.run_mfg_tool({"product_id": "0x8000"}, {})
    assert res["ok"] is False
    assert "required" in res["error"].lower()


def test_hex_and_decimal_ids_are_accepted():
    res = mfg_runner.run_mfg_tool(
        {"vendor_id": "0xFFF1", "product_id": "32768", "count": "1"}, {}
    )
    assert res["ok"] is True, res.get("error")
    # outdir is keyed by hex vid_pid -> confirms 0xFFF1 / 32768(0x8000) parsed
    assert any("fff1_8000" in n for n in _zip_names(res))


# --- the four "Device attestation (DAC)" modes -----------------------------

def test_mode_none_has_no_dac(tmp_path):
    """Dropdown: 'No DAC — commissioning data only'."""
    res = mfg_runner.run_mfg_tool(
        {"vendor_id": "0xFFF1", "product_id": "0x8000", "count": "1"}, {}
    )
    assert res["ok"] is True, res.get("error")
    assert len(res["devices"]) == 1
    dev = res["devices"][0]
    assert dev["passcode"] and dev["discriminator"] and dev["qrcode_png_b64"]
    names = _zip_names(res)
    assert any(n.endswith("-partition.bin") for n in names)
    assert not any("DAC_cert" in n for n in names)


def test_mode_bundled_paa_generates_dac():
    """Dropdown: 'Bundled test certs' — PAA works with any VID/PID."""
    res = mfg_runner.run_mfg_tool(
        {"vendor_id": "0xFFF1", "product_id": "0x8000", "count": "1",
         "paa": True, "cert": PAA_CERT[0], "key": PAA_KEY[0]},
        _files(PAA_CERT, PAA_KEY),
    )
    assert res["ok"] is True, res.get("error")
    assert any("DAC_cert.pem" in n for n in _zip_names(res))


def test_mode_bundled_pai_generates_dac():
    """Dropdown: 'Bundled test PAI' — fixed to VID 0xFFF2 / PID 0x8001."""
    res = mfg_runner.run_mfg_tool(
        {"vendor_id": "0xFFF2", "product_id": "0x8001", "count": "1",
         "pai": True, "cert": PAI_CERT[0], "key": PAI_KEY[0],
         "cert_dclrn": CD_DER[0]},
        _files(PAI_CERT, PAI_KEY, CD_DER),
    )
    assert res["ok"] is True, res.get("error")
    assert any("DAC_cert.pem" in n for n in _zip_names(res))


def test_mode_custom_with_matching_dac_and_pai():
    """Dropdown: 'Custom' — user uploads a DAC + the PAI that signed it."""
    res = mfg_runner.run_mfg_tool(
        {"vendor_id": "0xFFF2", "product_id": "0x8001", "count": "1",
         "pai": True, "cert": PAI_CERT[0], "key": PAI_KEY[0],
         "dac_cert": DAC_CERT[0], "dac_key": DAC_KEY[0]},
        _files(PAI_CERT, PAI_KEY, DAC_CERT, DAC_KEY),
    )
    assert res["ok"] is True, res.get("error")
    assert any("DAC_cert" in n for n in _zip_names(res))


def test_mode_custom_mismatched_dac_pai_is_rejected():
    """A DAC from one chain + a PAI from another must fail (the reported bug)."""
    res = mfg_runner.run_mfg_tool(
        {"vendor_id": "0xFFF2", "product_id": "0x8001", "count": "1",
         "pai": True, "cert": PAI_CERT[0], "key": PAI_KEY[0],
         "dac_cert": DAC_FFF1_CERT[0], "dac_key": DAC_FFF1_KEY[0]},
        _files(PAI_CERT, PAI_KEY, DAC_FFF1_CERT, DAC_FFF1_KEY),
    )
    assert res["ok"] is False
    assert "chain" in res["error"].lower() or "mismatch" in (res.get("log", "") + res["error"]).lower()


# --- misc behavior ---------------------------------------------------------

def test_multiple_devices():
    res = mfg_runner.run_mfg_tool(
        {"vendor_id": "0xFFF1", "product_id": "0x8000", "count": "3"}, {}
    )
    assert res["ok"] is True, res.get("error")
    assert len(res["devices"]) == 3
    assert sum(n.endswith("-partition.bin") for n in _zip_names(res)) == 3


def test_state_reset_between_runs():
    """Two back-to-back runs must not leak device state into each other."""
    cfg = {"vendor_id": "0xFFF1", "product_id": "0x8000", "count": "2"}
    first = mfg_runner.run_mfg_tool(dict(cfg), {})
    second = mfg_runner.run_mfg_tool(dict(cfg, count="1"), {})
    assert first["ok"] and second["ok"]
    assert len(first["devices"]) == 2
    assert len(second["devices"]) == 1
