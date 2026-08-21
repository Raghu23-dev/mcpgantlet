"""A minimal MCP server built strictly to spec 2026-07-28.

Its only purpose is criterion 3: the auditor must report ZERO failures against it. A
conformance checker that flags a correct server is worse than no checker, because the
first false positive teaches its user to ignore every subsequent report.

Deliberately has no tools and no features. It implements the transport rules and nothing
else, so any failure the auditor reports against it is a bug in the auditor.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

PROTOCOL_VERSION = "2026-07-28"
METHOD_NOT_FOUND = -32601
HEADER_MISMATCH = -32020

SENTINEL = re.compile(r"^=\?base64\?(.*)\?=$")


def _decode(raw: str | None) -> str | None:
    if raw is None:
        return None
    m = SENTINEL.match(raw)
    if m is None:
        return raw
    try:
        return base64.b64decode(m.group(1)).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return raw


def _err(rid: Any, code: int, message: str, status: int = 200) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}},
        status_code=status,
    )


def create_reference_app() -> FastAPI:
    app = FastAPI()

    @app.get("/mcp")
    async def get_mcp() -> Response:
        # The GET stream endpoint was removed in this revision.
        return Response(status_code=405, headers={"allow": "POST"})

    @app.delete("/mcp")
    async def delete_mcp() -> Response:
        # DELETE terminated a session; sessions no longer exist.
        return Response(status_code=405, headers={"allow": "POST"})

    @app.post("/mcp")
    async def post_mcp(request: Request) -> Response:
        # Origin MUST be validated to prevent DNS rebinding.
        origin = request.headers.get("origin")
        if origin is not None and not origin.startswith(("http://localhost", "http://127.0.0.1")):
            return _err(None, HEADER_MISMATCH, "origin not allowed", 403)

        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            return _err(None, HEADER_MISMATCH, "body must be JSON", 400)
        if not isinstance(body, dict):
            return _err(None, HEADER_MISMATCH, "body must be an object", 400)

        rid = body.get("id")
        # Bound to locals before the isinstance check so the narrowing is provable. The
        # `x.get(k) if isinstance(x.get(k), dict) else {}` form calls .get twice and mypy
        # cannot tie the two calls together, so `params`/`meta` stayed Optional and every
        # later .get() was an error under strict mode.
        raw_method = body.get("method")
        method = raw_method if isinstance(raw_method, str) else ""
        raw_params = body.get("params")
        params: dict[str, Any] = raw_params if isinstance(raw_params, dict) else {}
        raw_meta = params.get("_meta")
        meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}

        # MCP-Protocol-Version is required and must agree with the body's _meta.
        version = request.headers.get("mcp-protocol-version")
        if version is None:
            return _err(rid, HEADER_MISMATCH, "missing MCP-Protocol-Version", 400)
        body_version = meta.get("io.modelcontextprotocol/protocolVersion")
        if isinstance(body_version, str) and body_version != version:
            return _err(rid, HEADER_MISMATCH, "version header does not match body", 400)
        if version != PROTOCOL_VERSION:
            return _err(rid, HEADER_MISMATCH, f"unsupported version {version}", 400)

        # Mcp-Method and Mcp-Name mirror body fields; a mismatch is rejected.
        method_header = request.headers.get("mcp-method")
        if method_header is not None and method_header != method:
            return _err(rid, HEADER_MISMATCH, "Mcp-Method does not match body", 400)
        name_header = _decode(request.headers.get("mcp-name"))
        body_name = params.get("name") or params.get("uri")
        if name_header is not None and isinstance(body_name, str) and name_header != body_name:
            return _err(rid, HEADER_MISMATCH, "Mcp-Name does not match body", 400)

        # A notification has no id: 202 with no body.
        if rid is None:
            return Response(status_code=202)

        if method == "ping":
            return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {}})
        if method == "tools/list":
            return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {"tools": []}})

        # Unknown method: 404 with -32601.
        return _err(rid, METHOD_NOT_FOUND, f"Method not found: {method}", 404)

    return app
