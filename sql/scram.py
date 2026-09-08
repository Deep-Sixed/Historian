#!/usr/bin/env python3
"""Compute a PostgreSQL SCRAM-SHA-256 verifier client-side.

WHY THIS EXISTS. PostgreSQL logs full statement text on error, so any statement of the
form `ALTER ROLE x PASSWORD '<plaintext>'` can put the password into the server log the
moment anything in it fails. Piping the statement via stdin instead of -c does NOT help:
the server receives the same SQL either way. That distinction matters — an earlier version
of provision.sh claimed stdin prevented the leak, which was false; it only moved detection
after the fact.

Sending a VERIFIER instead is genuine prevention. `ALTER ROLE x PASSWORD
'SCRAM-SHA-256$...'` is accepted by PostgreSQL as a pre-computed verifier, so the plaintext
never crosses the wire and never enters a log — a failed statement discloses only a salted
hash, which is what the server would have stored anyway.

Format: SCRAM-SHA-256$<iterations>:<b64 salt>$<b64 StoredKey>:<b64 ServerKey>
"""

import base64
import hashlib
import hmac
import os
import sys

ITERATIONS = 4096


def verifier(password: str, salt: bytes | None = None, iterations: int = ITERATIONS) -> str:
    # SASLprep is a no-op for the ASCII url-safe tokens we generate; non-ASCII passwords
    # would need it before this point.
    salt = salt or os.urandom(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations, 32)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    b64 = lambda b: base64.b64encode(b).decode()
    return (f"SCRAM-SHA-256${iterations}:{b64(salt)}$"
            f"{b64(stored_key)}:{b64(server_key)}")


if __name__ == "__main__":
    # password arrives on stdin so it never appears in argv or the process table
    sys.stdout.write(verifier(sys.stdin.readline().rstrip("\n")))
