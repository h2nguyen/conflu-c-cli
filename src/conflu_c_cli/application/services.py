"""What a feature area needs to build its use cases: the ports and the settings, in one object, so that a new area changes no signature."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .ports import Clock, ConfigStore, ConfluenceGateway, Diagnostics, Files
from .settings import Settings


@dataclass(frozen=True)
class Services:
    gateway: ConfluenceGateway
    settings: Settings
    diagnostics: Diagnostics
    files: Files
    clock: Clock
    store: ConfigStore
    environ: Mapping[str, str]
