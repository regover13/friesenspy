"""VAPID-Keys für Web Push Notifications generieren.

Ausgabe direkt in config.env-Format (Wert auf einer Zeile, \n escaped).
Keys einmalig ausführen und in /opt/friesenspy/config.env eintragen.
"""
from cryptography.hazmat.primitives.asymmetric.ec import generate_private_key, SECP256R1
from cryptography.hazmat.primitives.serialization import (
    Encoding, PublicFormat, PrivateFormat, NoEncryption,
)
import base64

key = generate_private_key(SECP256R1())
pub = key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
pem = key.private_bytes(Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()).decode()

pub_b64 = base64.urlsafe_b64encode(pub).decode().rstrip("=")
pem_escaped = pem.replace("\n", "\\n")

print(f"VAPID_PUBLIC_KEY={pub_b64}")
print(f"VAPID_PRIVATE_KEY={pem_escaped}")
print("VAPID_CONTACT_EMAIL=mailto:your@email.com")
