"""
Serve the API and the dashboard together on one origin.

    python serve_all.py
    ->  dashboard  http://localhost:8000
        API docs   http://localhost:8000/docs

Why this exists
---------------
Opening frontend/index.html directly from disk cannot work: browsers treat every
`file://` document as a unique opaque origin and refuse to load ES modules from
it. The dashboard must be served over HTTP.

Running it here, mounted under the API itself, means the browser sees a single
origin — so the default `API_BASE` (same origin + /api/v1) resolves correctly and
CORS never enters the picture. That mirrors what nginx.conf does in production.

Alternatives
------------
Two processes, if you prefer them separate:
    uvicorn app.main:app --reload            # API on :8000
    cd frontend && python -m http.server 5173
Then uncomment __MEWS_API_BASE__ in frontend/index.html to point at :8000.
"""

from pathlib import Path

import uvicorn
from fastapi.staticfiles import StaticFiles

from app.main import app

FRONTEND = Path(__file__).parent / "frontend"

if not FRONTEND.is_dir():
    raise SystemExit(f"frontend/ not found next to {Path(__file__).name}")

class NoCacheStatic(StaticFiles):
    """Serve the dashboard without letting the browser hold on to it.

    There is no build step, so filenames never change when the code does. A
    browser that caches `src/config.js` therefore keeps running last week's
    dashboard after an edit, and the only visible symptom is that a change
    "did not take" — which is indistinguishable from a bug in the change.

    `no-store` costs a re-download of a few small files per load and removes the
    whole class of problem. Production serves through nginx, which sets its own
    caching policy, so this only affects the local launcher.
    """

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        return response


# Mounted last and at the root, so every /api/v1 route already registered by
# app.main keeps priority; StaticFiles only sees what the API did not claim.
app.mount("/", NoCacheStatic(directory=FRONTEND, html=True), name="dashboard")


def _basemap_host() -> str:
    """Report which tile provider the served config actually names."""
    import re
    cfg = (FRONTEND / "src" / "config.js").read_text(encoding="utf-8")
    m = re.search(r"tileUrl:\s*'https://([^/']+)", cfg)
    return m.group(1) if m else "unknown"


if __name__ == "__main__":
    print("Dashboard  ->  http://localhost:8000")
    print("API docs   ->  http://localhost:8000/docs")
    # Printed so a stale-cache problem is distinguishable from a wrong config:
    # if this says arcgisonline and the browser still shows a CARTO watermark,
    # the browser is serving you an old copy, not the server.
    print(f"Basemap    ->  {_basemap_host()}  (static files sent with no-store)")
    uvicorn.run(app, host="127.0.0.1", port=8000)
