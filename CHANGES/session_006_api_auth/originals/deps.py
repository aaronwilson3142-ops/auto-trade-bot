"""FastAPI dependency helpers for APIS API routes.

Import these Annotated aliases into route files to get type-annotated
request-scoped dependencies with one import line.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from apps.api.state import ApiAppState, get_app_state
from config.settings import Settings, get_settings

AppStateDep = Annotated[ApiAppState, Depends(get_app_state)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
