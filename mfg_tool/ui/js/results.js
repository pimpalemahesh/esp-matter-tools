/**
 * Convert Pyodide toJs() Maps and decode base64-wrapped binaries from Python.
 */

export function mapToObject(item) {
  if (item instanceof Map) {
    const obj = {};
    for (const [key, value] of item) {
      obj[key] = mapToObject(value);
    }
    return obj;
  }
  if (Array.isArray(item)) {
    return item.map(mapToObject);
  }
  return item;
}

export function decodeContent(content) {
  const obj = mapToObject(content);
  if (obj && typeof obj === 'object' && obj._b64 === true && obj.data) {
    const binary = atob(obj.data);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    return bytes;
  }
  return obj;
}
