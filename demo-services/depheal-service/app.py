"""Missing-dependency demo: wcwidth is NOT preinstalled on purpose.
First boot crashes with ModuleNotFoundError; AeroOps pip-installs it,
restarts, and the service goes healthy — true bug resolution."""
import http.server

import wcwidth  # noqa: F401 — healed automatically if missing


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = f"dep healed ok wcwidth={wcwidth.__version__}".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


http.server.HTTPServer(("127.0.0.1", 4121), H).serve_forever()
