from typing import Literal

from pydantic import BaseModel


class Preferences(BaseModel):
    theme: Literal["light", "dark", "system"] = "system"
    stream_responses: bool = True
    default_model: str = "jat-development"
    memory_enabled: bool = True
    chat_history_enabled: bool = True
    analytics_enabled: bool = False
    reduced_motion: bool = False
