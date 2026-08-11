"""HTTP route for provider-aware model configuration options.

Mounted from ``app/main.py`` behind the same ``get_current_user`` dependency
as every other authenticated route - this module doesn't import
``authentication`` itself, since that's a composition-root concern (see
``.claude/rules/architecture.md``, "Dependency injection").
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from model.schemas import ModelCatalogResponse, ModelOptionResponse, TemperatureOptionsResponse

from infrastructure.llm.protocol import LanguageModelClient

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=ModelCatalogResponse)
async def get_model_catalog(request: Request) -> ModelCatalogResponse:
    """List provider-native chat models and generation defaults."""
    catalog: LanguageModelClient = request.app.state.model_catalog
    snapshot = await catalog.available_models()
    return ModelCatalogResponse(
        provider=catalog.provider_name,
        default_model=catalog.default_model,
        models=[ModelOptionResponse(id=model, label=model) for model in snapshot.models],
        temperature=TemperatureOptionsResponse(
            min=0,
            max=2,
            step=0.1,
            default=catalog.default_temperature,
        ),
    )
