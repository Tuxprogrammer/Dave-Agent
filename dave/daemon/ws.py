"""A minimal RFC 6455 WebSocket client for one plain ws:// connection to DaveBridge. Standard library only.

DaveBridge sits on the stack's internal network (ws://gtnh:25580 in production, ws://127.0.0.1:25580 in dev), so
there is no TLS and no proxy. Text frames carry one JSON object each (DaveBridge PROTOCOL.md section 1).

Supports: the HTTP upgrade with an Authorization header, masked client frames, fragmented messages, ping/pong and
the close handshake. Server-side helpers (accept_key, read_frame with masked input, encode_frame unmasked) are
here too so the tests can run a fake bridge with the same code.
"""

import asyncio
import base64
import hashlib
import os
import struct
from urllib.parse import urlsplit

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
OP_CONT, OP_TEXT, OP_BINARY, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA
MAX_MESSAGE = 4 * 1024 * 1024      # DaveBridge messages are small; refuse anything absurd


class ConnectionClosed(Exception):
    def __init__(self, code=1006, reason=""):
        super().__init__("websocket closed (%s) %s" % (code, reason))
        self.code, self.reason = code, reason


class HandshakeError(Exception):
    pass


def accept_key(key):
    return base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()


def encode_frame(opcode, payload, mask):
    head = bytes([0x80 | opcode])
    n = len(payload)
    mbit = 0x80 if mask else 0
    if n < 126:
        head += bytes([mbit | n])
    elif n < 65536:
        head += bytes([mbit | 126]) + struct.pack("!H", n)
    else:
        head += bytes([mbit | 127]) + struct.pack("!Q", n)
    if not mask:
        return head + payload
    key = os.urandom(4)
    return head + key + bytes(b ^ key[i % 4] for i, b in enumerate(payload))


async def read_frame(reader):
    """Returns (fin, opcode, payload). Unmasks masked frames (client to server)."""
    b0, b1 = await reader.readexactly(2)
    fin, opcode, masked, n = bool(b0 & 0x80), b0 & 0x0F, bool(b1 & 0x80), b1 & 0x7F
    if n == 126:
        n = struct.unpack("!H", await reader.readexactly(2))[0]
    elif n == 127:
        n = struct.unpack("!Q", await reader.readexactly(8))[0]
    if n > MAX_MESSAGE:
        raise ConnectionClosed(1009, "frame too large")
    key = await reader.readexactly(4) if masked else None
    data = await reader.readexactly(n)
    if key:
        data = bytes(b ^ key[i % 4] for i, b in enumerate(data))
    return fin, opcode, data


class WebSocket:
    """One client connection. recv() returns text messages; control frames are handled inside."""

    def __init__(self, reader, writer, mask=True):
        self._r, self._w, self._mask = reader, writer, mask
        self._send_lock = asyncio.Lock()
        self.closed = False
        self.close_code = None

    @classmethod
    async def connect(cls, url, headers=None, timeout=10):
        u = urlsplit(url)
        if u.scheme != "ws":
            raise HandshakeError("only ws:// is supported, got %r" % url)
        host, port = u.hostname, u.port or 80
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        lines = ["GET %s HTTP/1.1" % (u.path or "/"), "Host: %s:%d" % (host, port), "Upgrade: websocket",
                 "Connection: Upgrade", "Sec-WebSocket-Key: " + key, "Sec-WebSocket-Version: 13"]
        lines += ["%s: %s" % kv for kv in (headers or {}).items()]
        try:
            writer.write(("\r\n".join(lines) + "\r\n\r\n").encode())
            await asyncio.wait_for(writer.drain(), timeout)
            raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError, ConnectionError) as e:
            writer.close()                      # never leave the socket open on a failed handshake
            raise HandshakeError("no HTTP response to the upgrade (%s)" % type(e).__name__) from e
        except BaseException:
            writer.close()
            raise
        status, *hdrs = raw.decode("latin-1").split("\r\n")
        if " 101 " not in status + " ":
            writer.close()
            raise HandshakeError("upgrade refused: %s" % status.strip())
        got = {h.split(":", 1)[0].strip().lower(): h.split(":", 1)[1].strip() for h in hdrs if ":" in h}
        if got.get("sec-websocket-accept") != accept_key(key):
            writer.close()
            raise HandshakeError("bad Sec-WebSocket-Accept")
        return cls(reader, writer)

    async def send(self, text):
        await self._send(OP_TEXT, text.encode("utf-8"))

    async def _send(self, opcode, payload):
        if self.closed:
            raise ConnectionClosed(self.close_code or 1006)
        async with self._send_lock:
            try:
                self._w.write(encode_frame(opcode, payload, self._mask))
                await self._w.drain()
            except (ConnectionError, RuntimeError) as e:
                self.closed = True
                raise ConnectionClosed(1006, str(e)) from e

    async def recv(self):
        """The next text message. Raises ConnectionClosed when the connection ends."""
        parts, kind = [], None
        while True:
            try:
                fin, opcode, data = await read_frame(self._r)
            except (asyncio.IncompleteReadError, ConnectionError) as e:
                self.closed = True
                raise ConnectionClosed(1006, "connection lost") from e
            if opcode == OP_PING:
                await self._send(OP_PONG, data)
                continue
            if opcode == OP_PONG:
                continue
            if opcode == OP_CLOSE:
                code = struct.unpack("!H", data[:2])[0] if len(data) >= 2 else 1005
                reason = data[2:].decode("utf-8", "replace")
                if not self.closed:
                    try:
                        await self._send(OP_CLOSE, data[:2])
                    except ConnectionClosed:
                        pass
                self.closed, self.close_code = True, code
                self._w.close()
                raise ConnectionClosed(code, reason)
            if opcode in (OP_TEXT, OP_BINARY):
                parts, kind = [data], opcode
            elif opcode == OP_CONT and kind is not None:
                parts.append(data)
            else:
                continue
            if sum(map(len, parts)) > MAX_MESSAGE:
                raise ConnectionClosed(1009, "message too large")
            if fin:
                if kind == OP_TEXT:
                    return b"".join(parts).decode("utf-8")
                parts, kind = [], None           # DaveBridge never sends binary; ignore it

    async def close(self, code=1000, timeout=5):
        if self.closed:
            return
        try:
            await asyncio.wait_for(self._send(OP_CLOSE, struct.pack("!H", code)), timeout)
        except (ConnectionClosed, asyncio.TimeoutError):
            self.abort()                        # a peer that stopped reading must not hang the close
            return
        self.closed, self.close_code = True, code
        self._w.close()

    def abort(self):
        """Drops the connection at once (no close handshake). A pending recv() then raises ConnectionClosed."""
        self.closed = True
        self.close_code = self.close_code or 1006
        try:
            self._w.transport.abort()
        except (AttributeError, RuntimeError):
            self._w.close()
