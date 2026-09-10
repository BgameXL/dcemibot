"""Socket client for the DCEMI headless recipe renderer.

Talks to a DCEMI instance over TCP. A short connection is openes per request.

Protocol:
  /list [query] -> JSON array line
  /recipe <item> [uses] -> JSON array line (or {"error": ...})
  /render <recipe_id> -> 4-byte big-endian length + PNG bytes (0 = error)
"""

import os
import json
import struct
import asyncio

HOST = os.getenv("DCEMI_HOST", "127.0.0.1")
PORT = int(os.getenv("DCEMI_PORT", "25599"))


class DcemiError(Exception):
    pass


async def _exchange(command: str, binary: bool):
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(HOST, PORT), timeout=5)
    except (OSError, asyncio.TimeoutError) as e:
        raise DcemiError(f"DCEMI renderer offline ({HOST}:{PORT})") from e

    try:
        writer.write((command + "\n").encode("utf-8"))
        await writer.drain()
        if binary:
            n = struct.unpack(">I", await reader.readexactly(4))[0]
            return await reader.readexactly(n) if n else None
        return json.loads((await reader.readline()).decode("utf-8"))
    except (OSError, asyncio.IncompleteReadError, ValueError) as e:
        raise DcemiError(str(e)) from e
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass


async def recipes(item: str, uses: bool = False):
    cmd = f"/recipe {item}{' uses' if uses else ''}".strip()
    return await _exchange(cmd, binary=False)


async def render(recipe_id: str) -> bytes | None:
    return await _exchange(f"/render {recipe_id}", binary=True)


async def search(query: str) -> list[str]:
    result = await _exchange(f"/list {query}".strip(), binary=False)
    return result if isinstance(result, list) else []
