"""The routes of the mock Confluence for the templates of a space. `MockConfluence` asks them before its own routes (see mock_extensions.py).

Templates exist in the v1 API only: `GET /rest/api/template/page` (the page templates of a space, or the global ones without `spaceKey`),
`GET /rest/api/template/blueprint` (the templates that blueprints provide) and `GET /rest/api/template/{contentTemplateId}`. The lists page with `start` and
`limit` and say in `_links.next` where the next piece starts; a body comes only with `expand=body` or `expand=body.storage`. A template that does not exist is
HTTP 403, as the document says, and so is a list of a space that does not exist. Nothing writes a template.

The ids 7400 to 7499 belong to this area; a blueprint of the space ENG has the id of a UUID. The mock starts with (the same as `fakes_templates.py` holds):

    page templates       7401 "Meeting notes template" (global)      7402 "Release checklist" (ENG)     7403 "Incident report" (ENG, with a mention and an e-mail address)
                         7404 "Decision record" (ENG, a variable twice and one with an entity)           7405 "How-to page" (DOCS)
    blueprint templates  7406 "Meeting notes" (global)               7407 "Product requirements" (global)
                         7408a0b1-c2d3-4e5f-8a6b-7c8d9e0f1a2b "Retrospective" (ENG)

Every list is in the order of the names.
"""
from __future__ import annotations

import re
import urllib.parse
from typing import Any

from .mock_base import RequestError, Routes

ACCOUNT = "5b10ac8d82e05b22cc7d4ef5"  # the user of the token of the mock
INCIDENT_BODY = (
    f'<p>What happened?</p><p>Contact <ac:link><ri:user ri:account-id="{ACCOUNT}" /></ac:link> '
    "or write to alex@example.com.</p>"
)
MEETING_BLUEPRINT = "com.atlassian.confluence.plugins.confluence-business-blueprints:meeting-notes-blueprint"
FIRST_NEW_ID = 7409
LAST_NEW_ID = 7499
EXPANDS = {"body", "body.storage"}


class TemplatesRoutes(Routes):
    def __init__(self, mock: Any) -> None:
        super().__init__(mock)
        self.templates: dict[str, dict[str, Any]] = {}
        self._next = FIRST_NEW_ID
        if mock.populated:
            self._seed()

    # -- the data --------------------------------------------------------------------------------

    def add_template(
        self,
        name: str,
        body: str = "",
        *,
        kind: str = "page",
        space_key: str = "",
        description: str = "",
        labels: tuple[str, ...] = (),
        blueprint: str = "",
        template_id: str = "",
    ) -> str:
        """A template for a test to set up (and its id). An empty `space_key` makes it a global one."""
        if kind not in ("page", "blueprint"):
            raise ValueError(kind)
        if space_key and self.mock._space_by_key(space_key) is None:
            raise KeyError(space_key)
        if not template_id:
            if self._next > LAST_NEW_ID:
                raise RequestError(500, "The mock has no id left", f"This mock hands out the ids {FIRST_NEW_ID} to {LAST_NEW_ID} for new templates", old=True)
            template_id = str(self._next)
            self._next += 1
        self.templates[template_id] = {
            "templateId": template_id,
            "name": name,
            "description": description,
            "templateType": kind,
            "spaceKey": space_key,
            "labels": list(labels),
            "blueprint": blueprint,
            "body": body,
        }
        return template_id

    def _seed(self) -> None:
        add = self.add_template
        add("Meeting notes template", '<h1><at:var at:name="title" /></h1><p>Date: <at:var at:name="Meeting date" /></p><p><ac:placeholder>@Pick the attendees</ac:placeholder></p>',
            description="Notes of a meeting", labels=("meeting",), template_id="7401")
        add("Release checklist", '<h2>Release <at:var at:name="version" /></h2><ul><li>Update the notes</li><li>Tag <at:var at:name="version" /></li></ul>',
            space_key="ENG", description="Steps for every release", labels=("release", "checklist"), template_id="7402")
        add("Incident report", INCIDENT_BODY, space_key="ENG", template_id="7403")
        add("Decision record", "<p><at:var at:name='title'/></p><p><at:var at:name=\"title\" /></p><p><at:var at:name=\"Tom &amp; Jerry\" at:rawxhtml=\"a>b\"/></p>",
            space_key="ENG", description="ADR style", labels=("adr",), template_id="7404")
        add("How-to page", "<p>Steps</p>", space_key="DOCS", description="A guide in steps", template_id="7405")
        add("Meeting notes", '<h1><at:var at:name="title" /></h1><p>Goals</p>', kind="blueprint", description="Agenda, notes and actions", labels=("meeting",),
            blueprint=MEETING_BLUEPRINT, template_id="7406")
        add("Product requirements", '<p>Goals</p><p><at:var at:name="owner" /></p>', kind="blueprint", description="What and why",
            blueprint="com.atlassian.confluence.plugins.confluence-software-blueprints:requirements-blueprint", template_id="7407")
        add("Retrospective", "<p>Went well</p>", kind="blueprint", space_key="ENG", description="What went well", labels=("retro",),
            blueprint="com.atlassian.confluence.plugins.confluence-software-blueprints:retrospectives-blueprint", template_id="7408a0b1-c2d3-4e5f-8a6b-7c8d9e0f1a2b")

    def _model(self, template: dict[str, Any], expand: list[str]) -> dict[str, Any]:
        """A template as the document describes it. A global template has no `space`; the body is there when it was asked for."""
        model: dict[str, Any] = {
            "templateId": template["templateId"],
            "name": template["name"],
            "description": template["description"],
            "labels": [{"prefix": "global", "name": name, "id": str(index), "label": name} for index, name in enumerate(template["labels"], 1)],
            "templateType": template["templateType"],
            "editorVersion": "v2",
        }
        if template["blueprint"]:
            model["referencingBlueprint"] = template["blueprint"]
        if template["templateType"] == "blueprint":
            plugin, _, module = template["blueprint"].partition(":")
            model["originalTemplate"] = {"pluginKey": plugin or "com.atlassian.confluence.plugins.confluence-create-content-plugin", "moduleKey": module or template["templateId"]}
        if template["spaceKey"]:
            space = self.mock._space_by_key(template["spaceKey"]) or {}
            model["space"] = {"id": int(space.get("id", 0)), "key": template["spaceKey"], "name": space.get("name", ""), "type": "global", "status": "current"}
        if "body" in expand or "body.storage" in expand:
            model["body"] = {"storage": {"value": template["body"], "representation": "storage", "embeddedContent": []}}
        else:
            model["_expandable"] = {"body": ""}
        model["_links"] = {"self": f"{self.mock.base_url}/rest/api/template/{urllib.parse.quote(template['templateId'])}"}
        return model

    # -- the routes ------------------------------------------------------------------------------

    def handle(self, handler: Any, method: str, path: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]], body: Any) -> bool:
        found = self.match(r"/rest/api/template/([^/]+)", path)
        if found is None or method != "GET":
            return False
        handler._require_known_query(query, {"spaceKey", "start", "limit", "expand"} if found.group(1) in ("page", "blueprint") else {"expand"}, old=True)
        expand = handler._parse_csv(handler._single(query, "expand"), "expand", old=True)
        unknown = [value for value in expand if value not in EXPANDS]
        if unknown:
            raise RequestError(400, "Bad Request", f"Unsupported value for expand: {unknown[0]}", old=True, old_key="BAD_REQUEST")
        if found.group(1) in ("page", "blueprint"):
            self._list(handler, found.group(1), query, query_pairs, expand)
            return True
        template = self.templates.get(found.group(1))
        if template is None:
            raise RequestError(403, "Forbidden", "There is no template with this id, or you may not see it", old=True, old_key="FORBIDDEN")
        handler._reply_json(200, self._model(template, expand))
        return True

    def _list(self, handler: Any, kind: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]], expand: list[str]) -> None:
        key = handler._single(query, "spaceKey") or ""
        if key and self.mock._space_by_key(key) is None:
            raise RequestError(403, "Forbidden", "You may not see the templates of this space", old=True, old_key="FORBIDDEN")
        limit = handler._parse_limit(query, default=25, old=True)
        raw = handler._single(query, "start")
        if raw is not None and not re.fullmatch(r"[0-9]+", raw):
            raise RequestError(400, "Bad Request", "start must be an integer", old=True, old_key="BAD_REQUEST")
        start = int(raw or 0)
        found = sorted(
            (item for item in self.templates.values() if item["templateType"] == kind and item["spaceKey"] == key),
            key=lambda item: (item["name"].casefold(), item["templateId"]),
        )
        size = min(limit, self.mock.page_cap)
        shown = found[start : start + size]
        links: dict[str, Any] = {"base": self.mock.base_url, "context": self.mock.context_path or "/"}
        if start + size < len(found):
            pairs = [(name, value) for name, value in query_pairs if name != "start"] + [("start", str(start + size))]
            links["next"] = f"/rest/api/template/{kind}?{urllib.parse.urlencode(pairs)}"
        handler._reply_json(200, {"results": [self._model(item, expand) for item in shown], "start": start, "limit": size, "size": len(shown), "_links": links})
