"""The in-memory Confluence for the labels used in a space, besides the labels of a page: a mixin of `FakeGateway` (`_init_labels` sets up its state)."""
from __future__ import annotations

from conflu_c_cli.domain.errors import NotFoundError
from conflu_c_cli.domain.model import Chunk, Label


class FakeLabels:
    def _init_labels(self) -> None:
        pass

    def list_space_labels(self, space_id: str, *, limit: int = 25, cursor: str = "") -> Chunk[Label]:
        """The labels of the pages of the space, by name, two at a time like every list of the fake."""
        self._enter("list_space_labels", space_id, limit, cursor)
        if space_id not in {space.id for space in self.spaces.values()}:
            raise NotFoundError(f"Not found: GET /api/v2/spaces/{space_id}/content/labels", details={"status": 404})
        found = {(label.name, label.prefix): label for page in self.pages.values() if page.space_id == space_id for label in page.labels}
        return self._chunk(sorted(found.values(), key=lambda label: (label.name, label.prefix)), cursor, limit)
