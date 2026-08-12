"""Pydantic response models for the model-catalog route."""

from __future__ import annotations

from pydantic import BaseModel


class ModelOptionResponse(BaseModel):
    """One provider-native model selectable for an agent."""

    id: str
    label: str


class TemperatureOptionsResponse(BaseModel):
    """Supported per-agent sampling-temperature controls."""

    min: float
    max: float
    step: float
    default: float


class ModelCatalogResponse(BaseModel):
    """Provider-aware defaults and model options for agent configuration."""

    provider: str
    default_model: str
    models: list[ModelOptionResponse]
    temperature: TemperatureOptionsResponse
