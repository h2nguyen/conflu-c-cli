"""`conflu setup --discover`: the address of the Atlassian gateway of a site, from the tenant information that the site itself publishes.

An API token is not accepted on the custom domain of a Confluence Cloud site, and a token with scopes belongs on the gateway address
`https://api.atlassian.com/ex/confluence/CLOUD_ID`. The cloud id is in the public tenant information of the site, which is read without
any credential. This module finds it and proposes the address; asking the person, and printing, are the command's business.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..domain.errors import ConfigError
from .ports import ConfluenceGateway
from .session import ConfigService
from .settings import Settings, gateway_address, gateway_cloud_id, host_of, shown_address


@dataclass(frozen=True)
class TenantProposal:
    current: str  # CONFLUENCE_BASE_URL as it is now, with a user name or password left out
    site: str  # the host of that address
    cloud_id: str
    gateway_address: str
    already: bool  # the current address is the gateway address: there is nothing to change


class DiscoverTenant:
    def __init__(self, gateway: ConfluenceGateway, settings: Settings, config: ConfigService) -> None:
        self._gateway = gateway
        self._settings = settings
        self._config = config

    def propose(self) -> TenantProposal:
        """Asks the host of CONFLUENCE_BASE_URL, and only that host, for its cloud id. When the address is the gateway address already it
        is the cloud id that says so, and nothing is asked of anybody."""
        base_url = self._settings.base_url
        if not base_url:
            raise ConfigError(
                "CONFLUENCE_BASE_URL is not set.",
                hint="Run `conflu config set CONFLUENCE_BASE_URL https://example.atlassian.net` first: `conflu setup --discover` asks that site for its cloud id.",
            )
        if "@" in base_url:
            raise ConfigError(
                "CONFLUENCE_BASE_URL contains a user name or password (or an @ that looks like one): nothing was asked.",
                hint="Take it out: the e-mail address and the token are set apart.",
            )
        current, site = shown_address(base_url), host_of(base_url)
        known = gateway_cloud_id(base_url)
        if known:
            return TenantProposal(current, site, known, gateway_address(known), True)
        cloud_id = self._gateway.tenant_info(base_url)
        return TenantProposal(current, site, cloud_id, gateway_address(cloud_id), False)

    def apply(self, proposal: TenantProposal) -> None:
        """Saves the gateway address as CONFLUENCE_BASE_URL, through the same checks as `conflu config set`."""
        self._config.set_value("CONFLUENCE_BASE_URL", proposal.gateway_address)
