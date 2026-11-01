"""The templates of a space: the REST calls. A mixin of `RestConfluenceGateway`, which provides `_call`, `_finish`, `_transport`, `_settings`,
`_next_cursor` and `_base`."""
from __future__ import annotations

from typing import TYPE_CHECKING

from ...domain.errors import UnavailableError
from .rest_support import V1, query, quote

# The models and the mapper of this area are imported where they are used, so that a command that never reads it does not load them (tests/test_startup.py).
if TYPE_CHECKING:
    from ...domain.templates import Template, TemplatePage

# The calls of this area that use the v1 API, each with why v2 does not do (see docs/reference/compatibility.md). All of them: v2 has no templates.
V1_CALLS: dict[str, str] = {
    "GET /rest/api/template/page": "v2 has no templates: it cannot list the page templates of a space or the global ones.",
    "GET /rest/api/template/blueprint": "v2 has no templates: it cannot list the templates that blueprints provide.",
    "GET /rest/api/template/{contentTemplateId}": "v2 has no templates: it cannot read one template with its body.",
}


class RestTemplates:
    def list_templates(self, *, space_key: str = "", blueprints: bool = False, limit: int = 25, start: int = 0) -> TemplatePage:
        from .map_templates import page_from

        kind = "blueprint" if blueprints else "page"
        data = self._call("GET", f"{V1}/template/{kind}?{query(spaceKey=space_key, start=start, limit=limit)}")
        return page_from(data, start)

    def get_template(self, template_id: str) -> Template:
        from .map_templates import template_from

        data = self._call("GET", f"{V1}/template/{quote(template_id)}?{query(expand='body.storage')}")
        template = template_from(data)
        if not template.id:
            raise UnavailableError(f"Confluence answered, but not with template {template_id}.", hint="Try again; if it stays, check the id with `conflu templates`.")
        return template
