from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme: Literal["dark", "light", "system"] = "dark"
    locale: Literal["en", "he"] = "en"
    compact: bool = False
    reduce_motion: bool = False
    show_sources: bool = True
    show_tool_activity: bool = True
    high_contrast: bool = False
    auto_read_responses: bool = False
    send_on_enter: bool = True
    sidebar_default_open: bool = True
    speech_voice_en: str = Field(default="preferred", max_length=512)
    speech_voice_he: str = Field(default="preferred", max_length=512)
    speech_input_locale: Literal["auto", "en", "he"] = "auto"


class SettingsResponse(WorkspaceSettings):
    updated_at: datetime | None = None
