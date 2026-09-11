"""Public SDK hosting: the zero-dependency browser snippet.

No auth by design (it is embedded in third-party pages). Served with a
long-ish cache; publishers pin updates by re-copying the snippet URL.
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

router = APIRouter(tags=["sdk"])

SDK_PATH = Path(__file__).resolve().parents[2] / "static" / "aeroops.js"


@router.get("/sdk/aeroops.js", include_in_schema=False)
def serve_sdk() -> Response:
    try:
        body = SDK_PATH.read_bytes()
    except OSError:
        raise HTTPException(status_code=404, detail="SDK not found")
    return Response(content=body, media_type="application/javascript",
                    headers={"Cache-Control": "public, max-age=3600"})
