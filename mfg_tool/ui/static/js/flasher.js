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

(function () {
  const ESPTOOL_CDN = "https://cdn.jsdelivr.net/npm/esptool-js@0.5.7/bundle.js";

  let mod = null;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const isSupported = () => "serial" in navigator;

  async function flashDevice(partitionB64, offset, { onLog, onProgress }) {
    if (!isSupported()) throw new Error("Web Serial is not available in this browser.");
    const log = onLog || (() => { });
    if (!mod) mod = await import(ESPTOOL_CDN);
    const { ESPLoader, Transport } = mod;

    const port = await navigator.serial.requestPort();
    const transport = new Transport(port);
    const loader = new ESPLoader({
      transport,
      baudrate: 115200,
      romBaudrate: 115200,
      enableTracing: false,
      terminal: { clean() { }, writeLine: (d) => log(d), write: (d) => log(d) },
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
      try {
        await transport.setRTS(true);
        await sleep(100);
        await loader.after();
      } catch (e) { /* best-effort */ }
      try { await transport.disconnect(); } catch (e) { /* ignore */ }
    }
  }

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
