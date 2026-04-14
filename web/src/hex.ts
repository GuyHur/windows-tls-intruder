/** Decode a base64 string into a Uint8Array. */
export function b64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64);
  const arr = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
  return arr;
}

/** Encode a Uint8Array into a base64 string. */
export function bytesToB64(bytes: Uint8Array): string {
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
}

/** Format bytes as a classic hex dump (offset | hex | ascii). */
export function hexDump(bytes: Uint8Array, cols = 16): string {
  const lines: string[] = [];
  for (let off = 0; off < bytes.length; off += cols) {
    const slice = bytes.slice(off, off + cols);
    const hex = Array.from(slice)
      .map((b) => b.toString(16).padStart(2, "0"))
      .join(" ")
      .padEnd(cols * 3 - 1, " ");
    const ascii = Array.from(slice)
      .map((b) => (b >= 0x20 && b < 0x7f ? String.fromCharCode(b) : "."))
      .join("");
    lines.push(`${off.toString(16).padStart(8, "0")}  ${hex}  |${ascii}|`);
  }
  return lines.join("\n");
}

/** Parse a whitespace-separated hex string (like "48 65 6c 6c 6f") back to bytes. */
export function parseHex(hex: string): Uint8Array {
  const tokens = hex.trim().split(/\s+/);
  const arr = new Uint8Array(tokens.length);
  for (let i = 0; i < tokens.length; i++) arr[i] = parseInt(tokens[i], 16);
  return arr;
}
