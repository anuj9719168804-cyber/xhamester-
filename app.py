"""Standalone xHamster-only resolver API."""
import logging
import time
from collections import defaultdict, deque

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

import config
import xhamster_resolver

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("xhamster_api")

app = FastAPI(
    title="xHamster Resolver API",
    description="Standalone xHamster-only video resolver API.",
    version="1.0.0",
)

_hits: dict[str, deque] = defaultdict(deque)
EXAMPLE_URL = "https://xhamster.com/videos/example-video-name-1234567"


def _check_rate_limit(client_ip: str):
    now = time.time()
    window = _hits[client_ip]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= config.RATE_LIMIT_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Rate limit exceeded, try again in a bit.")
    window.append(now)


@app.get("/", include_in_schema=False)
def root():
    return {
        "status": True,
        "creator": "xHamster API",
        "message": "xHamster Resolver API is online",
        "version": "1.0.0",
        "example": {
            "url": EXAMPLE_URL,
            "resolve": f"/api/xhamster?url={EXAMPLE_URL}",
        },
        "endpoints": {
            "resolve": "/api/xhamster?url=<XHAMSTER_VIDEO_URL>",
            "health": "/health",
        },
    }


@app.get("/health")
def health():
    return {"status": True, "service": "xhamster-api", "provider": "xHamster"}


@app.get("/api/xhamster")
async def xhamster(url: str = Query(..., description="xHamster video link")):
    if not xhamster_resolver.is_xhamster_link(url):
        return JSONResponse(
            status_code=400,
            content={"status": False, "error": "Only xHamster links are supported here."},
        )
    try:
        data = await run_in_threadpool(xhamster_resolver.resolve_xhamster, url)
    except Exception as e:
        logger.warning("xHamster resolve failed for %s: %s", url, e)
        return JSONResponse(status_code=502, content={"status": False, "error": str(e)})
    return {"status": True, "data": data, "credit": "Ak"}


@app.middleware("http")
async def rate_limit_mw(request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    try:
        _check_rate_limit(client_ip)
    except HTTPException as e:
        return JSONResponse(status_code=e.status_code, content={"status": False, "error": e.detail})
    return await call_next(request)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=config.PORT, reload=False)
