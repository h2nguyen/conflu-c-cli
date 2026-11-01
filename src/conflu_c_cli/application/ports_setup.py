"""The part of the Confluence port that is about setting up the address of the site. `ConfluenceGateway` inherits it.

The one operation needs no credential: the tenant information of a Confluence Cloud site is public, and it is read before the credentials
are set up (or while they do not work, on the custom domain of a site).
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class SetupPort(ABC):
    @abstractmethod
    def tenant_info(self, base_url: str) -> str:
        """The cloud id of the site at `base_url`, from its public tenant information (`/_edge/tenant_info` at the root of that host). Nothing is
        sent to any other host and no credential is sent at all. ConfigError when the answer is not that of a Confluence Cloud site."""
