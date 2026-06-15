// Direct-to-device flashing over Web Serial using esptool-js. Chromium only;
// the CDN bundle loads lazily on first use. Exposes window.MfgFlasher.
//
// Each flash is self-contained: connect (sync once), write, reset the chip to
// run its firmware, release the port. The reset uses the ESP Web Tools sequence
// (assert RTS, then chip-specific release) which leaves the chip and DTR/RTS
// lines clean so the next flash connects reliably without a physical replug.
(function () {
  const ESPTOOL_CDN = "https://cdn.jsdelivr.net/npm/esptool-js@0.5.7/bundle.js";

  let mod = null;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const isSupported = () => "serial" in navigator;

  async function flashDevice(partitionB64, offset, { onLog, onProgress }) {
    if (!isSupported()) throw new Error("Web Serial is not available in this browser.");
    const log = onLog || (() => {});
    if (!mod) mod = await import(ESPTOOL_CDN);
    const { ESPLoader, Transport } = mod;

    const port = await navigator.serial.requestPort();
    const transport = new Transport(port);
    const loader = new ESPLoader({
      transport,
      baudrate: 115200,
      romBaudrate: 115200,
      enableTracing: false,
      terminal: { clean() {}, writeLine: (d) => log(d), write: (d) => log(d) },
    });

    try {
      const chip = await loader.main();
      log("Connected: " + chip);
      await loader.writeFlash({
        fileArray: [{ data: atob(partitionB64), address: offset }],
        flashSize: "keep",
        eraseAll: false,
        compress: true,
        reportProgress: (_i, written, total) => onProgress(total ? written / total : 0),
      });
      log("Flash complete; resetting device.");
      return chip;
    } finally {
      // Reset to run firmware and leave the lines clean for the next connect.
      try {
        await transport.setRTS(true);
        await sleep(100);
        await loader.after();
      } catch (e) { /* best-effort */ }
      try { await transport.disconnect(); } catch (e) { /* ignore */ }
    }
  }

  // Parse an ESP-IDF partition table (CSV text or binary) into
  // [{name, type, subtype, offset}]. Offsets are numbers.
  function parsePartitionTable(filename, bytes) {
    if (bytes[0] === 0xaa && bytes[1] === 0x50) return parseBinary(bytes);
    return parseCsv(new TextDecoder().decode(bytes));
  }

  function parseCsv(text) {
    const out = [];
    for (const raw of text.split(/\r?\n/)) {
      const line = raw.trim();
      if (!line || line.startsWith("#")) continue;
      const c = line.split(",").map((s) => s.trim());
      if (c.length < 4 || !c[3]) continue;
      const offset = parseInt(c[3], c[3].startsWith("0x") ? 16 : 10);
      if (Number.isNaN(offset)) continue;
      out.push({ name: c[0], type: c[1], subtype: c[2], offset });
    }
    return out;
  }

  function parseBinary(bytes) {
    const out = [];
    const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    for (let i = 0; i + 32 <= bytes.length; i += 32) {
      if (bytes[i] !== 0xaa || bytes[i + 1] !== 0x50) break;
      const label = new TextDecoder()
        .decode(bytes.subarray(i + 12, i + 28))
        .replace(/\0.*$/, "");
      out.push({
        name: label,
        type: String(bytes[i + 2]),
        subtype: String(bytes[i + 3]),
        offset: dv.getUint32(i + 4, true),
      });
    }
    return out;
  }

  window.MfgFlasher = { isSupported, flashDevice, parsePartitionTable };
})();
