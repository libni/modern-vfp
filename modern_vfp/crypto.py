"""
Suite Criptográfica y de Seguridad (`modern_vfp/crypto.py`) para FoxNext / Modern VFP.
Proporciona:
- Checksum xBase compatible con Visual FoxPro: `SYS(2007, cExp [, nFlags])`
- Resúmenes criptográficos: `HASH(cExp, [cAlgoritmo])` (SHA256, MD5, SHA512, SHA1)
- Firmas digitales HMAC: `HMAC(cMensaje, cClave, [cAlgoritmo])`
- Cifrado simétrico reversible: `ENCRYPT(cTexto, cClave)` y `DECRYPT(cEncriptado, cClave)`
"""

from __future__ import annotations
import base64
import hashlib
import hmac
import os
from typing import Any, Optional
import zlib


def sys_2007(expr: Any, flags: int = 0) -> str:
    """
    Calcula el Checksum / CRC-32 de una expresión, compatible con Visual FoxPro SYS(2007).
    Devuelve el valor numérico en formato de cadena.
    """
    if expr is None:
        expr = ""
    data_bytes = str(expr).encode("utf-8")
    crc = zlib.crc32(data_bytes) & 0xFFFFFFFF
    return str(crc)


def hash_data(expr: Any, algorithm: str = "sha256") -> str:
    """
    Genera un hash criptográfico en hexadecimal (sha256, md5, sha512, sha1).
    """
    if expr is None:
        expr = ""
    data = str(expr).encode("utf-8")
    algo = algorithm.lower().strip()
    if algo not in hashlib.algorithms_available:
        algo = "sha256"
    h = hashlib.new(algo, data)
    return h.hexdigest()


def hmac_sign(message: Any, key: str, algorithm: str = "sha256") -> str:
    """
    Genera una firma HMAC (por defecto SHA-256) para autenticación de mensajes y APIs.
    """
    msg_bytes = str(message if message is not None else "").encode("utf-8")
    key_bytes = str(key).encode("utf-8")
    algo = algorithm.lower().strip()
    return hmac.new(key_bytes, msg_bytes, getattr(hashlib, algo, hashlib.sha256)).hexdigest()


def _derive_keystream(key_bytes: bytes, salt: bytes, length: int) -> bytes:
    """Deriva un keystream pseudoaleatorio seguro usando encadenamiento SHA-256."""
    stream = bytearray()
    counter = 0
    while len(stream) < length:
        block = hashlib.sha256(key_bytes + salt + counter.to_bytes(4, "big")).digest()
        stream.extend(block)
        counter += 1
    return bytes(stream[:length])


def encrypt_data(text: str, key: str) -> str:
    """
    Cifra un texto con clave simétrica y empaqueta en Base64 seguro con Salt aleatorio.
    """
    if not text:
        return ""
    plaintext = str(text).encode("utf-8")
    salt = os.urandom(8)
    keystream = _derive_keystream(str(key).encode("utf-8"), salt, len(plaintext))
    ciphertext = bytes(p ^ k for p, k in zip(plaintext, keystream))
    # Empaquetar: salt (8 bytes) + ciphertext
    payload = salt + ciphertext
    return base64.b64encode(payload).decode("ascii")


def decrypt_data(ciphertext_b64: str, key: str) -> str:
    """
    Descifra un texto cifrado en Base64 con la clave original.
    """
    if not ciphertext_b64:
        return ""
    try:
        payload = base64.b64decode(ciphertext_b64.encode("ascii"))
        if len(payload) < 8:
            return ""
        salt = payload[:8]
        ciphertext = payload[8:]
        keystream = _derive_keystream(str(key).encode("utf-8"), salt, len(ciphertext))
        decrypted = bytes(c ^ k for c, k in zip(ciphertext, keystream))
        return decrypted.decode("utf-8")
    except Exception:
        return ""
