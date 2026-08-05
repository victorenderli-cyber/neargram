"""Gera um par de chaves VAPID para Web Push.

Uso:
    python tools/gen_vapid.py

Copie as chaves para as variáveis de ambiente do Render:
    VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_SUBJECT
"""
import base64

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid

v = Vapid()
v.generate_keys()

pub = v.public_key
priv = v.private_key

public_b64 = base64.urlsafe_b64encode(
    pub.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
).rstrip(b"=").decode()

private_b64 = base64.urlsafe_b64encode(
    priv.private_numbers().private_value.to_bytes(32, "big")
).rstrip(b"=").decode()

print("VAPID_PUBLIC_KEY=" + public_b64)
print("VAPID_PRIVATE_KEY=" + private_b64)
print("VAPID_SUBJECT=mailto:admin@neargram.app")
print()
print("Publique apenas VAPID_PUBLIC_KEY no repositório/seu código.")
print("VAPID_PRIVATE_KEY é secreta: configure-a somente no ambiente (Render).")
