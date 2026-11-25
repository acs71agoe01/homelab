#!/usr/bin/env python3
"""Lightweight streaming HTTP proxy that wakes a GPU Ollama host via Wake-on-LAN on demand."""
import http.client
import http.server
import json
import os
import socket
import subprocess
import threading
import time

LISTEN_HOST = os.getenv("WOL_PROXY_HOST", "0.0.0.0")
LISTEN_PORT = int(os.getenv("WOL_PROXY_PORT", "11435"))
TARGET_HOST = os.getenv("OLLAMA_TARGET_HOST", "192.168.1.20")
TARGET_PORT = int(os.getenv("OLLAMA_TARGET_PORT", "11434"))
TARGET_MAC = os.getenv("OLLAMA_TARGET_MAC", "AA:BB:CC:DD:EE:FF")
BROADCAST_IP = os.getenv("WOL_BROADCAST_IP", "192.168.1.255")
CACHE_DIR = os.getenv("WOL_CACHE_DIR", "/var/lib/ollama-wol-proxy")
WOL_TIMEOUT_SEC = int(os.getenv("WOL_TIMEOUT_SEC", "90"))

WAKE_PREFIXES = ("/api/chat", "/api/generate", "/api/embed", "/api/embeddings", "/api/pull", "/v1/")
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
}

wol_lock = threading.Lock()


def target_is_up(timeout=1.5):
    try:
        with socket.create_connection((TARGET_HOST, TARGET_PORT), timeout=timeout):
            return True
    except OSError:
        return False


def wake_and_wait():
    if target_is_up():
        return True
    with wol_lock:
        if target_is_up():
            return True
        deadline = time.time() + WOL_TIMEOUT_SEC
        last_sent = 0.0
        while time.time() < deadline:
            if time.time() - last_sent >= 10.0:
                subprocess.run(["wakeonlan", "-i", BROADCAST_IP, TARGET_MAC], check=False)
                last_sent = time.time()
            if target_is_up(timeout=1.5):
                return True
            time.sleep(2.0)
        return False


def save_cache(name, data):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, name)
    with open(path + ".tmp", "wb") as f:
        f.write(data)
    os.replace(path + ".tmp", path)


def load_cache(name, default_bytes):
    path = os.path.join(CACHE_DIR, name)
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    return default_bytes


class OllamaWoLHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def send_json_bytes(self, status, data, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)
        self.wfile.flush()

    def handle_request(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length > 0 else None
        path = self.path
        should_wake = any(path.startswith(p) for p in WAKE_PREFIXES)

        if not target_is_up():
            if not should_wake:
                if path.startswith("/api/tags"):
                    return self.send_json_bytes(200, load_cache("tags.json", b'{"models":[]}'))
                if path.startswith("/api/version"):
                    return self.send_json_bytes(200, load_cache("version.json", b'{"version":"0.0.0"}'))
                if path.startswith("/api/ps"):
                    return self.send_json_bytes(200, b'{"models":[]}')
                if path in ("/", ""):
                    return self.send_json_bytes(200, b"Ollama is running", "text/plain")
                return self.send_json_bytes(503, b'{"error":"GPU node offline"}')

            if not wake_and_wait():
                return self.send_json_bytes(504, b'{"error":"Timed out waiting for GPU node"}')

        fwd_headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
        if body is not None:
            fwd_headers["Content-Length"] = str(len(body))

        conn = http.client.HTTPConnection(TARGET_HOST, TARGET_PORT, timeout=300)
        try:
            conn.request(self.command, path, body=body, headers=fwd_headers)
            resp = conn.getresponse()

            if resp.status == 200 and (path.startswith("/api/tags") or path.startswith("/api/version")):
                data = resp.read()
                save_cache("tags.json" if path.startswith("/api/tags") else "version.json", data)
                return self.send_json_bytes(resp.status, data, resp.getheader("Content-Type", "application/json"))

            self.send_response(resp.status, resp.reason)
            if resp.getheader("Content-Type"):
                self.send_header("Content-Type", resp.getheader("Content-Type"))
            cl = resp.getheader("Content-Length")
            if cl is not None and not resp.chunked:
                data = resp.read()
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_header("Transfer-Encoding", "chunked")
                self.send_header("Connection", "close")
                self.end_headers()
                while True:
                    chunk = resp.read1(4096)
                    if not chunk:
                        break
                    self.wfile.write(f"{len(chunk):x}\r\n".encode("ascii") + chunk + b"\r\n")
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except Exception as exc:
            self.send_json_bytes(502, json.dumps({"error": str(exc)}).encode("utf-8"))
        finally:
            conn.close()

    do_GET = do_POST = do_HEAD = do_DELETE = handle_request


if __name__ == "__main__":
    http.server.ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), OllamaWoLHandler).serve_forever()
