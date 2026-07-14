from __future__ import annotations

import os
from pathlib import Path


def run_studio(
    *,
    host: str = "127.0.0.1",
    port: int = 8787,
    catalog: Path | None = None,
    reload: bool = False,
) -> None:
    """Launch the thin Sakura Studio GUI (FastAPI + uvicorn)."""
    if catalog is not None:
        os.environ["SAKURA_CATALOG"] = str(catalog.resolve())

    import uvicorn

    uvicorn.run(
        "sakura.studio_app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )
