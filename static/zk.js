/**
 * Zero-knowledge decryption for private items, in the browser.
 *
 * The key lives in the URL fragment (#k=<base64url>) — fragments are never sent
 * to the server, so the server stays zero-knowledge. The wire format matches
 * app/core/security/zk.py: AES-256-GCM, token = base64url(nonce[12] || ct||tag),
 * key = base64url(32 bytes).
 */
(function () {
  function b64urlToBytes(s) {
    s = s.replace(/-/g, "+").replace(/_/g, "/");
    while (s.length % 4) s += "=";
    const bin = atob(s);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  async function run() {
    const nodes = document.querySelectorAll("[data-zk-cipher]");
    if (!nodes.length) return;
    const match = location.hash.match(/(?:^#|&)k=([^&]+)/);
    if (!match) return; // no key in the fragment → leave values locked

    let key;
    try {
      const raw = b64urlToBytes(decodeURIComponent(match[1]));
      key = await crypto.subtle.importKey("raw", raw, "AES-GCM", false, ["decrypt"]);
    } catch (_) {
      return;
    }

    for (const node of nodes) {
      const token = node.getAttribute("data-zk-cipher");
      if (!token) continue;
      try {
        const raw = b64urlToBytes(token);
        const nonce = raw.slice(0, 12);
        const ciphertext = raw.slice(12);
        const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: nonce }, key, ciphertext);
        node.textContent = new TextDecoder().decode(plain);
        node.classList.add("zk-unlocked");
      } catch (_) {
        node.textContent = "🔓 wrong key";
      }
    }
  }

  run();
})();
