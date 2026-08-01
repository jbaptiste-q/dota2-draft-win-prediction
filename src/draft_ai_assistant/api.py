"""FastAPI adapter for the frozen Draft Assistant v1 product contract."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .contracts import (
    AnalyzeDraftRequest,
    AnalyzeDraftResponse,
    HealthResponse,
    HeroCatalogResponse,
    ModelCardResponse,
    ReplacementComparisonRequest,
    ReplacementComparisonResponse,
)
from .service import DraftAssistantService, UnsupportedHeroError


WEB_DIRECTORY = Path(__file__).resolve().parent / "web"


def create_app(
    service: DraftAssistantService | None = None,
) -> FastAPI:
    """Create an app with an injectable, framework-independent service."""

    assistant = service or DraftAssistantService.from_default_snapshot()
    app = FastAPI(
        title="Dota 2 Draft Assistant",
        version="0.3.0",
        description=(
            "Experimental completed 5v5 pick-only probability analysis, "
            "exact additive hero contributions, and user-directed one-for-one "
            "scenario comparison. The development candidate failed its "
            "readiness gate; partial drafts, hero rankings, recommendations, "
            "ban effects, and live Liquipedia calls are not supported."
        ),
    )

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(WEB_DIRECTORY / "index.html")

    @app.get(
        "/api/v1/health",
        response_model=HealthResponse,
        tags=["system"],
    )
    def health() -> HealthResponse:
        return assistant.health()

    @app.get(
        "/api/v1/heroes",
        response_model=HeroCatalogResponse,
        tags=["drafts"],
    )
    def heroes() -> HeroCatalogResponse:
        return assistant.heroes()

    @app.get(
        "/api/v1/model-card",
        response_model=ModelCardResponse,
        tags=["model"],
    )
    def model_card() -> ModelCardResponse:
        return assistant.model_card()

    @app.post(
        "/api/v1/analyze",
        response_model=AnalyzeDraftResponse,
        tags=["drafts"],
    )
    def analyze(request: AnalyzeDraftRequest) -> AnalyzeDraftResponse:
        try:
            return assistant.analyze(request)
        except UnsupportedHeroError as error:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "unsupported_hero",
                    "message": str(error),
                    "hero_keys": list(error.hero_keys),
                },
            ) from error

    @app.post(
        "/api/v1/replacement-comparisons",
        response_model=ReplacementComparisonResponse,
        tags=["drafts"],
    )
    def compare_replacement(
        request: ReplacementComparisonRequest,
    ) -> ReplacementComparisonResponse:
        try:
            return assistant.compare_replacement(request)
        except UnsupportedHeroError as error:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "unsupported_hero",
                    "message": str(error),
                    "hero_keys": list(error.hero_keys),
                },
            ) from error

    app.mount(
        "/static",
        StaticFiles(directory=WEB_DIRECTORY),
        name="static",
    )
    return app


app = create_app()


__all__ = ["WEB_DIRECTORY", "app", "create_app"]
