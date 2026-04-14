"""
Concatenates the Frida JS agent from frida_scripts/ into a single string
ready for `session.create_script()`.

Follows the same concatenation pattern as Deluder: config.js → debug override
→ common.js → each library script wrapped in an IIFE with its own `module`
object.
"""

from __future__ import annotations

import json
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "frida_scripts"

AVAILABLE_SCRIPTS: frozenset[str] = frozenset(
    p.stem
    for p in SCRIPTS_DIR.glob("*.js")
    if p.stem not in ("config", "common", "_debug_agent")
)

SCRIPT_DEFAULTS: dict[str, dict] = {
    "winsock": {
        "libs": ["ws2_32.dll", "wsock32.dll"],
        "send": True,
        "sendto": True,
        "recv": True,
        "recvfrom": True,
        "WSASend": True,
        "WSASendTo": True,
        "WSARecv": True,
        "WSARecvFrom": True,
        "closesocket": True,
        "shutdown": True,
    },
    "openssl": {
        "libs": ["libssl", "openssl", "ssleay", "libeay", "libcrypto"],
        "SSL_write": True,
        "SSL_write_ex": True,
        "SSL_read": True,
        "SSL_read_ex": True,
        "SSL_shutdown": True,
    },
    "schannel": {
        "libs": ["Secur32.dll"],
        "EncryptMessage": True,
        "DecryptMessage": True,
    },
    "libc": {
        "libs": ["libc.so", "libsocket.so", "libpthread.so"],
        "send": True,
        "sendto": True,
        "recv": True,
        "recvfrom": True,
        "shutdown": True,
        "close": True,
    },
    "gnutls": {
        "libs": ["gnutls"],
        "gnutls_record_send": True,
        "gnutls_record_recv": True,
        "gnutls_bye": True,
    },
}


def _read_js(name: str) -> str:
    return (SCRIPTS_DIR / f"{name}.js").read_text(encoding="utf-8")


def _wrap_script(script_source: str) -> str:
    return f"""
(function() {{
    {script_source}
}}());
    """


def build_agent(script_names: list[str], *, debug: bool = False) -> str:
    """Return a single JS source string that Frida will inject."""
    source = ""

    source += _read_js("config")
    source += f"\nconfig.debug = {str(debug).lower()};\n"
    source += _read_js("common")

    for name in script_names:
        if name not in AVAILABLE_SCRIPTS:
            raise ValueError(
                f"Unknown script: {name!r}. Available: {sorted(AVAILABLE_SCRIPTS)}"
            )
        cfg = dict(SCRIPT_DEFAULTS.get(name, {}))

        source += "\n"
        script_source = "const module = {};"
        script_source += f"module.type = '{name}';"
        script_source += f"module.config = {json.dumps(cfg)};"
        script_source += _read_js(name)
        source += _wrap_script(script_source)

    if debug:
        debug_path = SCRIPTS_DIR / "_debug_agent.js"
        debug_path.write_text(source, encoding="utf-8")

    return source
