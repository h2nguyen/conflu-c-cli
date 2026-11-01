"""The in-memory Confluence for the templates of a space: a mixin of `FakeGateway` (`_init_templates` sets up its state).

What it holds when a test starts (ids 7400 to 7499 belong to this area; a blueprint of the space ENG has the id of a UUID, as a real blueprint does):

    page templates       7401 "Meeting notes template" (global)      7402 "Release checklist" (ENG)     7403 "Incident report" (ENG, with a mention and an e-mail address)
                         7404 "Decision record" (ENG, a variable twice and one with an entity)           7405 "How-to page" (DOCS)
    blueprint templates  7406 "Meeting notes" (global)               7407 "Product requirements" (global)
                         7408a0b1-c2d3-4e5f-8a6b-7c8d9e0f1a2b "Retrospective" (ENG)

Every list is in the order of the names; `page_cap` (2) is how many it answers with at most, so that the lists have a next piece.
"""
from __future__ import annotations

import dataclasses

from conflu_c_cli.domain.errors import AuthError
from conflu_c_cli.domain.templates import Template, TemplateInfo, TemplatePage

MEETING_BLUEPRINT = "com.atlassian.confluence.plugins.confluence-business-blueprints:meeting-notes-blueprint"
INCIDENT_BODY = (
    '<p>What happened?</p><p>Contact <ac:link><ri:user ri:account-id="5b10ac8d82e05b22cc7d4ef5" /></ac:link> '
    "or write to alex@example.com.</p>"
)


class FakeTemplates:
    def _init_templates(self) -> None:
        def template(template_id: str, name: str, kind: str, space: str, description: str, labels: tuple[str, ...], body: str, blueprint: str = "") -> Template:
            return Template(template_id, name, kind, description, space, labels, blueprint, body)

        found = [
            template("7401", "Meeting notes template", "page", "", "Notes of a meeting", ("meeting",),
                     '<h1><at:var at:name="title" /></h1><p>Date: <at:var at:name="Meeting date" /></p><p><ac:placeholder>@Pick the attendees</ac:placeholder></p>'),
            template("7402", "Release checklist", "page", "ENG", "Steps for every release", ("release", "checklist"),
                     '<h2>Release <at:var at:name="version" /></h2><ul><li>Update the notes</li><li>Tag <at:var at:name="version" /></li></ul>'),
            template("7403", "Incident report", "page", "ENG", "", (), INCIDENT_BODY),
            template("7404", "Decision record", "page", "ENG", "ADR style", ("adr",),
                     "<p><at:var at:name='title'/></p><p><at:var at:name=\"title\" /></p><p><at:var at:name=\"Tom &amp; Jerry\" at:rawxhtml=\"a>b\"/></p>"),
            template("7405", "How-to page", "page", "DOCS", "A guide in steps", (), "<p>Steps</p>"),
            template("7406", "Meeting notes", "blueprint", "", "Agenda, notes and actions", ("meeting",),
                     '<h1><at:var at:name="title" /></h1><p>Goals</p>', MEETING_BLUEPRINT),
            template("7407", "Product requirements", "blueprint", "", "What and why", (), "<p>Goals</p><p><at:var at:name=\"owner\" /></p>",
                     "com.atlassian.confluence.plugins.confluence-software-blueprints:requirements-blueprint"),
            template("7408a0b1-c2d3-4e5f-8a6b-7c8d9e0f1a2b", "Retrospective", "blueprint", "ENG", "What went well", ("retro",), "<p>Went well</p>",
                     "com.atlassian.confluence.plugins.confluence-software-blueprints:retrospectives-blueprint"),
        ]
        self.templates: dict[str, Template] = {item.id: item for item in found}

    # -- the port ---------------------------------------------------------------------------

    def list_templates(self, *, space_key: str = "", blueprints: bool = False, limit: int = 25, start: int = 0) -> TemplatePage:
        self._enter("list_templates", space_key, blueprints, limit, start)
        if space_key and space_key not in self.spaces:
            raise AuthError("Confluence refused this request (HTTP 403).", hint="Your account lacks the permission, or the space does not exist.", details={"status": 403})
        kind = "blueprint" if blueprints else "page"
        found = sorted(
            (item for item in self.templates.values() if item.type == kind and item.space_key == space_key),
            key=lambda item: (item.name.casefold(), item.id),
        )
        size = min(limit, self.page_cap)
        piece = found[start : start + size]
        following = start + size if start + size < len(found) else None
        fields = [field.name for field in dataclasses.fields(TemplateInfo)]
        return TemplatePage([TemplateInfo(**{name: getattr(item, name) for name in fields}) for item in piece], start, following)

    def get_template(self, template_id: str) -> Template:
        self._enter("get_template", template_id)
        if template_id not in self.templates:
            raise AuthError("Confluence refused this request (HTTP 403).", hint="Your account lacks the permission, or there is no such template.", details={"status": 403})
        return self.templates[template_id]
