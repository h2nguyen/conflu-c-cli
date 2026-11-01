"""The in-memory Confluence for setting up the address of the site: a mixin of `FakeGateway` (`_init_setup` sets up its state)."""
from __future__ import annotations


class FakeSetup:
    def _init_setup(self) -> None:
        self.cloud_id = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"  # what the tenant information of this site says

    def tenant_info(self, base_url: str) -> str:
        self._enter("tenant_info", base_url)
        return self.cloud_id
