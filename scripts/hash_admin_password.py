from __future__ import annotations

import base64
import getpass
import hashlib
import os


password = getpass.getpass("Admin passphrase: ").encode("utf-8")
salt = os.urandom(16)
iterations = 100_000  # Cloudflare Workers WebCrypto maximum.
digest = hashlib.pbkdf2_hmac("sha256", password, salt, iterations)
enc = lambda value: base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
print(f"pbkdf2${iterations}${enc(salt)}${enc(digest)}")
