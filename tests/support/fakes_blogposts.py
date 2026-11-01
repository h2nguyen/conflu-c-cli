"""The in-memory Confluence for blog posts: a mixin of `FakeGateway` (`_init_blogposts` sets up its state).

The blog posts 7101 to 7105 are the fixtures (ids 7100 to 7199 belong to this area): 7101 has a mention, an e-mail address, a macro and headings in its
body, two labels and three comments (a footer comment with a reply, and an inline comment); 7104 is in the trash. The comments are kept with the
comments of the pages, under the id of the blog post they are on."""
from __future__ import annotations

import dataclasses
from typing import Any

from conflu_c_cli.domain.errors import ConflictError, NotFoundError, ValidationError
from conflu_c_cli.domain.model import Chunk, Comment, Label, Page, User, VersionInfo

BLOGPOST_BODY = (
    '<h1>Release 2026.10</h1><p>Thanks to <ac:link><ri:user ri:account-id="5b10ac8d82e05b22cc7d4ef5" /></ac:link> and write to alex@example.com.</p>'
    "<h2>Highlights</h2><ul><li>Faster search</li><li>Better export</li></ul><h2>Known issues</h2><p>None so far.</p>"
    '<ac:structured-macro ac:name="info" ac:schema-version="1"><ac:rich-text-body><p>Upgrade notes follow.</p></ac:rich-text-body></ac:structured-macro>'
)


class FakeBlogposts:
    def _init_blogposts(self) -> None:
        self.blogposts: dict[str, Page] = {}
        for number, (title, space, body, version, labels, message, status) in {
            "7101": ("Release 2026.10 is out", "ENG", BLOGPOST_BODY, 3, ("release", "news"), "Added the known issues", "current"),
            "7102": ("Weekly update", "ENG", "<p>Nothing to report this week.</p>", 1, (), "", "current"),
            "7103": ("Docs news", "DOCS", "<p>New guides are online.</p>", 1, (), "", "current"),
            "7104": ("Old announcement", "ENG", "<p>Superseded.</p>", 1, (), "", "trashed"),
            "7105": ("Planning notes", "ENG", "<p>Topics for the planning meeting.</p><p>Agenda below.</p>", 2, ("planning",), "Added the agenda", "current"),
        }.items():
            self.blogposts[number] = self._sample_blogpost(number, title, space, body, version, labels, message, status)
            self.content_kinds[number] = "blogpost"
        self.comments["7101"] = [
            Comment("7151", "footer", "2026-10-13T10:00:00.000Z", "<p>Great news.</p>", 1, User(self._blogpost_author())),
            Comment("7152", "footer", "2026-10-13T11:00:00.000Z", "<p>Thanks!</p>", 1, User(self._blogpost_author()), "7151"),
            Comment("7153", "inline", "2026-10-13T12:00:00.000Z", "<p>Check this number.</p>", 1, User(self._blogpost_author()), "", "open"),
        ]

    @staticmethod
    def _blogpost_author() -> str:
        from .fakes import ACCOUNT  # imported here: fakes.py imports this module

        return ACCOUNT

    def _sample_blogpost(
        self, blogpost_id: str, title: str, space: str, body: str, version: int, labels: tuple[str, ...], message: str, status: str
    ) -> Page:
        from .fakes import BASE

        space_id = self.spaces[space].id
        created = "2026-10-12T09:00:00.000Z"
        updated = "2026-10-14T10:00:00.000Z" if version > 1 else created
        author = User(self._blogpost_author())
        return Page(
            id=blogpost_id,
            title=title,
            status=status,
            space_id=space_id,
            space_key=space,
            created=created,
            version=VersionInfo(version, updated, message, False, author),
            author=author,
            labels=[Label(name) for name in labels],
            body=body,
            url=f"{BASE}/spaces/{space}/blog/2026/10/12/{blogpost_id}/{title.replace(' ', '+')}",
            raw={"id": blogpost_id, "title": title, "authorId": author.account_id, "version": {"number": version, "authorId": author.account_id}},
        )

    def _blogpost(self, blogpost_id: str) -> Page:
        if blogpost_id not in self.blogposts:
            raise NotFoundError(f"Not found: GET /api/v2/blogposts/{blogpost_id}")
        return self.blogposts[blogpost_id]

    def get_blogpost(self, blogpost_id: str, *, with_body: bool = True) -> Page:
        self._enter("get_blogpost", blogpost_id, with_body)
        return dataclasses.replace(self._copy(self._blogpost(blogpost_id), with_body), labels=[])  # the labels come from `list_blogpost_labels`

    def list_blogposts(
        self, *, space_id: str = "", title: str = "", status: str = "current", sort: str = "", limit: int = 25, cursor: str = ""
    ) -> Chunk[Page]:
        self._enter("list_blogposts", space_id, title, status, sort, limit, cursor)
        found = [
            post
            for post in self.blogposts.values()
            if (not space_id or post.space_id == space_id) and (not title or post.title.casefold() == title.casefold()) and post.status == status
        ]
        key = {"id": lambda p: int(p.id), "created-date": lambda p: p.created, "modified-date": lambda p: p.updated}.get(sort.lstrip("-"), lambda p: int(p.id))
        found.sort(key=key, reverse=sort.startswith("-"))
        chunk = self._chunk(found, cursor, limit)
        return Chunk([self._copy(post, False) for post in chunk.items], chunk.cursor)

    def create_blogpost(self, payload: dict[str, Any]) -> Page:
        self._enter("create_blogpost", payload)
        space = next((space for space in self.spaces.values() if space.id == payload.get("spaceId")), None)
        if space is None:
            raise ValidationError("Unknown space")
        post = self._sample_blogpost(self._new_id(), payload["title"], space.key, payload["body"]["value"], 1, (), "", "current")
        self._save_version(post, 1)
        self.blogposts[post.id] = post
        self.content_kinds[post.id] = "blogpost"
        return self._copy(post, True)

    def update_blogpost(self, blogpost_id: str, payload: dict[str, Any]) -> Page:
        self._enter("update_blogpost", blogpost_id, payload)
        post = self._blogpost(blogpost_id)
        number = payload["version"]["number"]
        if number != (1 if payload.get("status") == "draft" else post.version_number + 1):
            raise ConflictError("Confluence reports a conflict (HTTP 409): Version conflict.")
        post.title, post.body = payload["title"], payload["body"]["value"]
        self._save_version(post, number, payload["version"].get("message", ""))
        return self._copy(post, True)

    def list_blogpost_labels(self, blogpost_id: str) -> list[Label]:
        self._enter("list_blogpost_labels", blogpost_id)
        return list(self._blogpost(blogpost_id).labels)

    def add_blogpost_labels(self, blogpost_id: str, payload: list[dict[str, str]]) -> list[Label]:
        self._enter("add_blogpost_labels", blogpost_id, payload)
        post = self._blogpost(blogpost_id)
        for item in payload:
            if item["name"] not in {label.name for label in post.labels}:
                post.labels.append(Label(item["name"], item.get("prefix", "global")))
        return list(post.labels)

    def list_blogpost_comments(self, blogpost_id: str, *, inline: bool = False, limit: int = 50, cursor: str = "") -> Chunk[Comment]:
        self._enter("list_blogpost_comments", blogpost_id, inline, limit, cursor)
        self._blogpost(blogpost_id)
        kind = "inline" if inline else "footer"
        roots = [comment for comment in self.comments.get(blogpost_id, []) if comment.kind == kind and not comment.parent_id]
        return self._chunk(roots, cursor, limit)
