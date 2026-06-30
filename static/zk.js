/**
 * Zero-knowledge decryption for private items, in the browser.
 *
 * Two modes (matching the ghost-suite / ghostbit model and the CLI in
 * app/core/security/zk.py); the server only ever holds ciphertext:
 *
 *  - Random key:  token = base64url(nonce[12] || ct||tag); the key lives in the
 *    URL fragment (#k=<base64url>), never sent to the server.
 *  - Passphrase:  token = "a2." + base64url(salt[16]) + "." + base64url(nonce||ct);
 *    the AES key is derived from a passphrase via Argon2id (hash-wasm), prompted
 *    in-page. The passphrase never leaves the browser.
 */
(function () {
  const ARGON2 = { parallelism: 1, iterations: 2, memorySize: 19456, hashLength: 32 };

  function b64urlToBytes(s) {
    s = s.replace(/-/g, "+").replace(/_/g, "/");
    while (s.length % 4) s += "=";
    const bin = atob(s);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  async function aesGcmDecrypt(keyBytes, raw) {
    const key = await crypto.subtle.importKey("raw", keyBytes, "AES-GCM", false, ["decrypt"]);
    const nonce = raw.slice(0, 12);
    const ct = raw.slice(12);
    const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: nonce }, key, ct);
    return new TextDecoder().decode(plain);
  }

  function set(node, text, ok) {
    node.textContent = text;
    if (ok) node.classList.add("zk-unlocked");
  }

  async function decryptRandomKey(nodes, keyB64) {
    let keyBytes;
    try {
      keyBytes = b64urlToBytes(decodeURIComponent(keyB64));
    } catch (_) {
      return;
    }
    for (const node of nodes) {
      try {
        set(node, await aesGcmDecrypt(keyBytes, b64urlToBytes(node.getAttribute("data-zk-cipher"))), true);
      } catch (_) {
        set(node, "🔓 wrong key", false);
      }
    }
  }

  async function decryptPassphrase(nodes, passphrase) {
    if (!window.hashwasm || !window.hashwasm.argon2id) {
      return;
    }
    for (const node of nodes) {
      const parts = node.getAttribute("data-zk-cipher").split(".");
      try {
        const salt = b64urlToBytes(parts[1]);
        const keyBytes = await window.hashwasm.argon2id({
          password: passphrase,
          salt,
          outputType: "binary",
          ...ARGON2,
        });
        set(node, await aesGcmDecrypt(keyBytes, b64urlToBytes(parts[2])), true);
      } catch (_) {
        set(node, "🔓 wrong passphrase", false);
      }
    }
  }

  function passphrasePrompt(onSubmit) {
    if (document.getElementById("zk-pp-box")) return;
    const box = document.createElement("div");
    box.id = "zk-pp-box";
    box.className = "flash";
    box.style.marginBottom = "12px";
    box.innerHTML =
      '🔒 Passphrase-protected items on this page. ' +
      '<input type="password" id="zk-pp" placeholder="passphrase" autocomplete="off"> ' +
      '<button type="button" id="zk-pp-go" class="btn-new">Unlock</button>';
    const host = document.querySelector(".container") || document.body;
    host.insertBefore(box, host.firstChild);
    document.getElementById("zk-pp-go").addEventListener("click", () => {
      onSubmit(document.getElementById("zk-pp").value);
    });
  }

  function run() {
    const nodes = Array.from(document.querySelectorAll("[data-zk-cipher]"));
    if (!nodes.length) return;

    const passphraseNodes = nodes.filter((n) => (n.getAttribute("data-zk-cipher") || "").startsWith("a2."));
    const randomNodes = nodes.filter((n) => !passphraseNodes.includes(n));

    const match = location.hash.match(/(?:^#|&)k=([^&]+)/);
    if (randomNodes.length && match) {
      decryptRandomKey(randomNodes, match[1]);
    }
    if (passphraseNodes.length) {
      passphrasePrompt((pass) => decryptPassphrase(passphraseNodes, pass));
    }
  }

  run();
})();
