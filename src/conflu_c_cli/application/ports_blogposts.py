"""The part of the Confluence port that is about blog posts. `ConfluenceGateway` inherits it.

A blog post is read into a `Page` (the same fields: id, title, status, space, version, labels, body), without a parent. Its comments are read
into `Comment`s like those of a page; the replies of a comment come from `list_replies`, which does not care what the comment is on.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..domain.model import Chunk, Comment, Label, Page



class BlogpostsPort(ABC):
    @abstractmethod
    def get_blogpost(self, blogpost_id: str, *, with_body: bool = True) -> Page:
        """The blog post with its current version, and its body in storage format when `with_body`. The labels come from `list_blogpost_labels`."""

    @abstractmethod
    def list_blogposts(
        self, *, space_id: str = "", title: str = "", status: str = "current", sort: str = "", limit: int = 25, cursor: str = ""
    ) -> Chunk[Page]:
        """The blog posts of a space, or of the whole site without `space_id`; without their bodies."""

    @abstractmethod
    def create_blogpost(self, payload: dict[str, Any]) -> Page:
        """Sends `payload` as it is (see `domain.blogposts.create_blogpost_payload`): what a dry run shows is what is sent."""

    @abstractmethod
    def update_blogpost(self, blogpost_id: str, payload: dict[str, Any]) -> Page:
        """Sends `payload` as it is (see `domain.blogposts.update_blogpost_payload`). A version that is not the next one is a ConflictError."""

    @abstractmethod
    def list_blogpost_labels(self, blogpost_id: str) -> list[Label]:
        """Every label of the blog post."""

    @abstractmethod
    def add_blogpost_labels(self, blogpost_id: str, payload: list[dict[str, str]]) -> list[Label]:
        """Adds the labels (see `domain.payloads.label_payload`) and keeps those that are there."""

    @abstractmethod
    def list_blogpost_comments(self, blogpost_id: str, *, inline: bool = False, limit: int = 50, cursor: str = "") -> Chunk[Comment]:
        """The comments at the top of the conversations on a blog post; the replies come from `list_replies`."""
