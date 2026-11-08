"""Day 21: a codec server, so the Temporal UI can show decrypted payloads to people with the key.

The UI never gets the key. When you view a workflow, your browser sends the encrypted payloads
to this server (on your machine), which decrypts them and sends them back. Turn it on in the UI:
the glasses icon at the top right -> Codec Server -> http://127.0.0.1:8888.

    PAYLOAD_KEY=... uv run --env-file .env python -m netops_temporal.tools.codec_server
"""

import base64
import os

from aiohttp import web
from google.protobuf import json_format
from temporalio.api.common.v1 import Payloads

from netops_temporal.codec import EncryptionCodec

UI_ORIGIN = "http://localhost:8233"


def make_app(codec: EncryptionCodec) -> web.Application:
    async def handle(request: web.Request, decode: bool) -> web.Response:
        payloads = json_format.Parse(await request.text(), Payloads())
        method = codec.decode if decode else codec.encode
        result = Payloads(payloads=await method(payloads.payloads))
        return web.json_response(text=json_format.MessageToJson(result), headers=cors())

    async def decode(request: web.Request) -> web.Response:
        return await handle(request, decode=True)

    async def encode(request: web.Request) -> web.Response:
        return await handle(request, decode=False)

    async def preflight(request: web.Request) -> web.Response:
        # The browser asks first whether the UI's page may call this server.
        return web.Response(headers=cors())

    app = web.Application()
    app.router.add_post("/decode", decode)
    app.router.add_post("/encode", encode)
    app.router.add_route("OPTIONS", "/{path:.*}", preflight)
    return app


def cors() -> dict[str, str]:
    return {
        "Access-Control-Allow-Origin": UI_ORIGIN,
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "content-type, x-namespace",
        "Access-Control-Allow-Credentials": "true",
    }


if __name__ == "__main__":
    key = base64.b64decode(os.environ["PAYLOAD_KEY"])
    web.run_app(make_app(EncryptionCodec(key)), host="127.0.0.1", port=8888)
