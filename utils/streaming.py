"""
NDJSON streaming helpers for Flask routes.

Đa số endpoint upload/processing trả về newline-delimited JSON. Trước đây
mỗi endpoint tự định nghĩa lại::

    def send(**kw):
        return _j.dumps(kw, ensure_ascii=False) + "\\n"
    ...
    return Response(stream_with_context(generate()), mimetype="application/x-ndjson")

Module này gom logic đó lại để các route chỉ cần::

    from utils.streaming import ndjson_line, ndjson_response

    def generate():
        yield ndjson_line(log="...", level="info")
        ...
    return ndjson_response(generate())
"""
from __future__ import annotations

import json
from typing import Any, Iterable

from flask import Response, stream_with_context


def ndjson_line(**fields: Any) -> str:
    """Serialize ``fields`` as a single NDJSON line (UTF-8 friendly).

    The trailing newline is required so frontends can split the stream
    on `\\n` reliably.
    """
    return json.dumps(fields, ensure_ascii=False) + "\n"


def ndjson_dump(data: Any) -> str:
    """Serialize an arbitrary object as one NDJSON line.

    Use when ``data`` is already a dict/list and you don't want to
    unpack with ``**``.
    """
    return json.dumps(data, ensure_ascii=False) + "\n"


def ndjson_response(generator: Iterable[str]) -> Response:
    """Wrap an iterator of NDJSON lines in a streaming Flask Response."""
    return Response(
        stream_with_context(generator),
        mimetype="application/x-ndjson",
    )
