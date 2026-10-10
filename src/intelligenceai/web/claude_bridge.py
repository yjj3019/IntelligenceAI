"""Immutable-image stdlib HTTP-to-Unix bridge; the actual provider key is absent."""

import base64
import hmac
import http.server
import json
import os
import socket
import struct
import subprocess
import sys
import threading

LIMIT = 2 * 1024 * 1024


def receive(stream, count):
    result = bytearray()
    while len(result) < count:
        chunk = stream.recv(count - len(result))
        if not chunk:
            raise ValueError("incomplete frame")
        result.extend(chunk)
    return bytes(result)


def main():
    descriptor = json.loads(sys.stdin.buffer.read(512 * 1024))
    capability = descriptor["capability"]

    class Relay(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            supplied = self.headers.get("x-api-key", "")
            length = self.headers.get("content-length", "")
            if (
                self.path != "/v1/messages"
                or not hmac.compare_digest(supplied, capability)
                or (
                    not length.isascii()
                    or not length.isdecimal()
                    or not 0 < int(length) <= 256 * 1024
                    or self.headers.get("transfer-encoding") is not None
                )
            ):
                self.send_error(403, "relay denied")
                return
            body = self.rfile.read(int(length))
            envelope = json.dumps(
                {"capability": capability, "body": base64.b64encode(body).decode()}
            ).encode()
            try:
                with socket.socket(socket.AF_UNIX) as stream:
                    stream.settimeout(descriptor["seconds"])
                    stream.connect("/relay/broker.sock")
                    stream.sendall(struct.pack("!I", len(envelope)) + envelope)
                    size = struct.unpack("!I", receive(stream, 4))[0]
                    if not 0 < size <= LIMIT:
                        raise ValueError("relay limit")
                    response = receive(stream, size)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)
            except Exception:
                self.send_error(502, "relay outcome unverified")

    server = http.server.HTTPServer(("127.0.0.1", 0), Relay)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    environment = {
        "HOME": "/home",
        "PATH": "/",
        "LANG": "C.UTF-8",
        "PYTHONHOME": "/usr",
        "ANTHROPIC_BASE_URL": "http://127.0.0.1:" + str(server.server_port),
        "ANTHROPIC_API_KEY": capability,
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "DISABLE_AUTOUPDATER": "1",
        "DISABLE_TELEMETRY": "1",
    }
    child = subprocess.Popen(
        descriptor["argv"],
        env=environment,
        stdin=subprocess.PIPE,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    child.communicate(descriptor["prompt"].encode())
    server.shutdown()
    os._exit(child.returncode if child.returncode >= 0 else 1)


if __name__ == "__main__":
    main()
