"""Memory-stress demo (safe): allocates only on demand via /stress endpoint."""
import http.server
import json

_chunks: list = []


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/stress":
            _chunks.append(bytearray(10 * 1024 * 1024))  # 10MB per hit, bounded below
            if len(_chunks) > 20:
                _chunks.clear()
            body = json.dumps({"allocated_mb": len(_chunks) * 10}).encode()
        else:
            body = b'{"status":"ok"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


http.server.HTTPServer(("127.0.0.1", 4102), Handler).serve_forever()
