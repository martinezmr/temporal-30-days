"""Day 21: encrypt every payload before it leaves this process.

Workflow inputs, results, activity arguments: Temporal stores them all in history, on the server,
for as long as the history is kept. Some of ours are sensitive (configs, device details). A
payload codec encrypts them on the way out of the worker or starter and decrypts them on the way
back in, so the server only ever holds ciphertext. Anyone without the key, including whoever runs
the server, sees `binary/encrypted`.
"""

import os
from collections.abc import Sequence

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from temporalio.api.common.v1 import Payload
from temporalio.converter import PayloadCodec

ENCODING = b"binary/encrypted"


class EncryptionCodec(PayloadCodec):
    def __init__(self, key: bytes, key_id: str = "netops-1") -> None:
        # The key ID goes into each payload's metadata, so after a key rotation you can tell
        # which key a payload needs.
        self.key_id = key_id
        self.aes = AESGCM(key)  # AES-256-GCM: encrypts, and detects tampering

    async def encode(self, payloads: Sequence[Payload]) -> list[Payload]:
        return [
            Payload(
                metadata={"encoding": ENCODING, "encryption-key-id": self.key_id.encode()},
                data=self._encrypt(p.SerializeToString()),
            )
            for p in payloads
        ]

    async def decode(self, payloads: Sequence[Payload]) -> list[Payload]:
        decoded = []
        for p in payloads:
            if p.metadata.get("encoding") != ENCODING:
                decoded.append(p)  # not ours (e.g. written before encryption was turned on)
                continue
            key_id = p.metadata.get("encryption-key-id", b"").decode()
            if key_id != self.key_id:
                raise ValueError(f"payload needs encryption key {key_id!r}, have {self.key_id!r}")
            decoded.append(Payload.FromString(self._decrypt(p.data)))
        return decoded

    def _encrypt(self, data: bytes) -> bytes:
        nonce = os.urandom(12)  # never reuse a nonce with the same key
        return nonce + self.aes.encrypt(nonce, data, None)

    def _decrypt(self, data: bytes) -> bytes:
        return self.aes.decrypt(data[:12], data[12:], None)
