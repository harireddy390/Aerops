# AeroOps setup

Requires: Python 3.12+, Node 20+, Ollama (optional, for AI second opinions).

```powershell
# backend
cd backend
pip install -r requirements.txt
python -m alembic upgrade head   # or auto create_all on boot
python -m uvicorn app.main:app --port 8000

# frontend (new terminal)
cd frontend
npm install
npm run dev                      # :5173, proxies /api -> :8000

# tests / lint
cd backend; python -m pytest tests/ -q
cd frontend; npx tsc --noEmit; npm run build

# docker
docker compose up --build        # backend :8000 + console :5173
```

Ollama: install, `ollama pull qwen2.5-coder:7b`, serve on :11434
(or set OLLAMA_ENABLED=false — rules still diagnose everything common).

Legacy Node MVP (v1.2.0) still runs: `npm start` (:3000). Its server was reused
as `demo-services/crash-service`.
