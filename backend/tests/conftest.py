"""Isolated test env: temp SQLite DB, monitor off, Ollama unreachable-but-fast,
no cloud key, no mailer (env vars beat backend/.env)."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="aeroops-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["MONITOR_ENABLED"] = "false"
os.environ["OLLAMA_ENABLED"] = "true"
os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:9"  # nothing listens: fast refusal
os.environ["OLLAMA_TIMEOUT_SEC"] = "3"
os.environ["OPENAI_API_KEY"] = ""
os.environ["SMTP_USER"] = ""
os.environ["SMTP_PASS"] = ""
os.environ["MAIL_TO"] = ""
os.environ["AUTH_ENABLED"] = "true"
os.environ["ALLOW_OPEN_SIGNUP"] = "false"
