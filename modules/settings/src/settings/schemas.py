from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class WorkspaceSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme: Literal["dark", "light", "system"] = "dark"
    locale: Literal["en", "he"] = "en"
    compact: bool = False
    reduce_motion: bool = False
    show_sources: bool = True
    show_tool_activity: bool = True


class SettingsResponse(WorkspaceSettings):
    updated_at: datetime | None = None
