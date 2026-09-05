"""Dependency-failure demo (safe): /health returns 500 until /fix-dependency is hit,
simulating an unavailable downstream that recovers."""
import http.server
import json

_broken = True


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        global _broken
        if self.path == "/fix-dependency":
            _broken = False
            body = b'{"dependency":"restored"}'
            self.send_response(200)
        elif self.path == "/break":
            _broken = True
            body = b'{"dependency":"broken"}'
            self.send_response(200)
        elif self.path == "/health":
            body = b'{"status":"ok"}' if not _broken else b'{"status":"dependency-down"}'
            self.send_response(200 if not _broken else 500)
        else:
            body = b'{"status":"ok"}'
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


http.server.HTTPServer(("127.0.0.1", 4103), Handler).serve_forever()
