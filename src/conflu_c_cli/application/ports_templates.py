"""The part of the Confluence port that is about the templates of a space. `ConfluenceGateway` inherits it.

Only the older REST API (v1) has templates, and it pages with `start` and `limit`. A template is read: no operation makes a page from one, because
the API has no call that does.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..domain.templates import Template, TemplatePage



class TemplatesPort(ABC):
    @abstractmethod
    def list_templates(self, *, space_key: str = "", blueprints: bool = False, limit: int = 25, start: int = 0) -> TemplatePage:
        """The page templates of the space, or the global ones without `space_key`; the templates that blueprints provide with `blueprints`. In the order
        Confluence gives them, from `start`, without their bodies; the page says where the next one starts."""

    @abstractmethod
    def get_template(self, template_id: str) -> Template:
        """The template with its body in storage format. Confluence answers the same (HTTP 403) for a template that does not exist and for one that
        this account may not see: that is an AuthError."""
