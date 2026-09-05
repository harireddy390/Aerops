"""Healthy demo: plain stdlib HTTP server. Always works. Port 4101."""
import http.server

http.server.test(HandlerClass=http.server.SimpleHTTPRequestHandler, port=4101)
