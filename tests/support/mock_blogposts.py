"""The routes of the mock Confluence for blog posts. `MockConfluence` asks them before its own routes (see mock_extensions.py).

The REST API v2 has a collection for blog posts (`/blogposts`) next to the one for pages: their list, read, create and update, the blog posts of a space,
their labels and their comments. The blog posts have ids of their own here (7101 to 7105 are the fixtures; ids 7100 to 7199 belong to this area; a blog post
that is created gets the next id of the pages) and are registered in `mock.content_kinds`, so that `POST /content/convert-ids-to-types` knows them. The one
call of the v1 API that is keyed by the id of any content, `POST /content/{id}/label`, is answered here for a blog post.
"""
from __future__ import annotations

import urllib.parse
from typing import Any

from .mock_base import RequestError, Routes

_LIST_STATUS = {"current", "deleted", "trashed"}  # what the document allows for the list calls
_SINGLE_STATUS = {"current", "trashed", "deleted", "historical", "draft"}
_SORTS = {"id", "-id", "created-date", "-created-date", "modified-date", "-modified-date"}
_COMMENT_SORTS = {"created-date", "-created-date", "modified-date", "-modified-date"}
_COMMENT_STATUS = {"current", "deleted", "trashed", "historical", "draft"}
_BODY_FORMATS = {"storage", "atlas_doc_format"}
_FORBIDDEN_LABEL_CHARS = set(" &?/:;'\"<>()[],@^#$%*+=\\{}|`~!")

RELEASE_BODY = (
    '<h1>Release 2026.10</h1><p>Thanks to <ac:link><ri:user ri:account-id="5b10ac8d82e05b22cc7d4ef5" /></ac:link> and write to alex@example.com.</p>'
    "<h2>Highlights</h2><ul><li>Faster search</li><li>Better export</li></ul><h2>Known issues</h2><p>None so far.</p>"
    '<ac:structured-macro ac:name="info" ac:schema-version="1"><ac:rich-text-body><p>Upgrade notes follow.</p></ac:rich-text-body></ac:structured-macro>'
)


class BlogpostsRoutes(Routes):
    def __init__(self, mock: Any) -> None:
        super().__init__(mock)
        self.account = next(iter(mock.users))
        self.blogposts: dict[str, dict[str, Any]] = {}
        self.comments: dict[str, dict[str, Any]] = {}
        if mock.populated:
            self._seed()

    # -- the data --------------------------------------------------------------------------------

    def add_blogpost(
        self, space_key: str, title: str, body: str = "", *, status: str = "current", labels: tuple[str, ...] = (), versions: int = 1, blogpost_id: str = ""
    ) -> str:
        """A blog post in a space, for a test to set up. `versions` makes that many; the body is the one of the last."""
        space = self.mock._space_by_key(space_key)
        if space is None:
            raise KeyError(space_key)
        if not blogpost_id:
            blogpost_id = str(self.mock._next_page)
            self.mock._next_page += 1
        created = self.mock._tick()
        self.blogposts[blogpost_id] = {
            "id": blogpost_id,
            "spaceId": space["id"],
            "title": title,
            "status": status,
            "authorId": self.account,
            "createdAt": created,
            "versions": [
                {"number": number, "createdAt": created if number == 1 else self.mock._tick(), "message": "Created" if number == 1 else "", "minorEdit": False, "authorId": self.account, "body": body}
                for number in range(1, max(versions, 1) + 1)
            ],
            "labels": sorted(name.lower() for name in labels),
        }
        self.mock.content_kinds[blogpost_id] = "blogpost"
        return blogpost_id

    def add_comment(self, blogpost_id: str, body: str, *, kind: str = "footer", parent_id: str | None = None, comment_id: str = "") -> str:
        if blogpost_id not in self.blogposts:
            raise KeyError(blogpost_id)
        if kind not in {"footer", "inline"}:
            raise ValueError(kind)
        comment_id = comment_id or str(self.mock._next_comment)
        if not comment_id.isdigit() or comment_id in self.comments:
            raise ValueError(comment_id)
        if comment_id == str(self.mock._next_comment):
            self.mock._next_comment += 1
        self.comments[comment_id] = {
            "id": comment_id,
            "kind": kind,
            "blogPostId": blogpost_id,
            "parentCommentId": parent_id,
            "authorId": self.account,
            "version": {"number": 1, "createdAt": self.mock._tick()},
            "body": body,
            "resolutionStatus": "open" if kind == "inline" else None,
        }
        return comment_id

    def _seed(self) -> None:
        def make(blogpost_id: str, title: str, space: str, bodies: list[tuple[str, str]], labels: tuple[str, ...], status: str = "current") -> None:
            created = "2026-10-12T09:00:00.000Z"
            self.blogposts[blogpost_id] = {
                "id": blogpost_id,
                "spaceId": self.mock._space_by_key(space)["id"],
                "title": title,
                "status": status,
                "authorId": self.account,
                "createdAt": created,
                "versions": [
                    {"number": number, "createdAt": f"2026-10-{11 + number}T09:00:00.000Z", "message": message, "minorEdit": False, "authorId": self.account, "body": body}
                    for number, (message, body) in enumerate(bodies, 1)
                ],
                "labels": sorted(labels),
            }
            self.mock.content_kinds[blogpost_id] = "blogpost"

        make("7101", "Release 2026.10 is out", "ENG", [("Created", "<p>Draft.</p>"), ("", "<h1>Release 2026.10</h1><p>Almost there.</p>"), ("Added the known issues", RELEASE_BODY)], ("release", "news"))
        make("7102", "Weekly update", "ENG", [("Created", "<p>Nothing to report this week.</p>")], ())
        make("7103", "Docs news", "DOCS", [("Created", "<p>New guides are online.</p>")], ())
        make("7104", "Old announcement", "ENG", [("Created", "<p>Superseded.</p>")], (), status="trashed")
        make("7105", "Planning notes", "ENG", [("Created", "<p>Topics for the planning meeting.</p>"), ("Added the agenda", "<p>Topics for the planning meeting.</p><p>Agenda below.</p>")], ("planning",))
        for comment_id, kind, parent, body, created in (
            ("7151", "footer", None, "<p>Great news.</p>", "2026-10-13T10:00:00.000Z"),
            ("7152", "footer", "7151", "<p>Thanks!</p>", "2026-10-13T11:00:00.000Z"),
            ("7153", "inline", None, "<p>Check this number.</p>", "2026-10-13T12:00:00.000Z"),
        ):
            self.comments[comment_id] = {
                "id": comment_id,
                "kind": kind,
                "blogPostId": "7101",
                "parentCommentId": parent,
                "authorId": self.account,
                "version": {"number": 1, "createdAt": created},
                "body": body,
                "resolutionStatus": "open" if kind == "inline" else None,
            }

    # -- the models ------------------------------------------------------------------------------

    def _space_key(self, post: dict[str, Any]) -> str:
        return self.mock.spaces[post["spaceId"]]["key"]

    def _links(self, post: dict[str, Any]) -> dict[str, str]:
        year, month, day = post["createdAt"][:10].split("-")
        webui = f"/spaces/{self._space_key(post)}/blog/{year}/{int(month)}/{int(day)}/{post['id']}/{urllib.parse.quote_plus(post['title'])}"
        return {"webui": webui, "editui": f"{webui}?edit=true", "tinyui": f"/x/{post['id']}"}

    def _model(self, post: dict[str, Any], *, body_format: str | None = None, version_number: int | None = None, include_version: bool = True) -> dict[str, Any]:
        version = post["versions"][-1] if version_number is None else next(item for item in post["versions"] if item["number"] == version_number)
        model: dict[str, Any] = {
            "id": post["id"],
            "status": post["status"],
            "title": post["title"],
            "spaceId": post["spaceId"],
            "authorId": post["authorId"],
            "createdAt": post["createdAt"],
            "_links": {**self._links(post), "base": self.mock.base_url},
        }
        if include_version:
            model["version"] = {"number": version["number"], "createdAt": version["createdAt"], "message": version["message"], "minorEdit": version["minorEdit"], "authorId": version["authorId"]}
        if body_format == "storage":
            model["body"] = {"storage": {"representation": "storage", "value": version["body"]}}
        return model

    def _listed(self, post: dict[str, Any], body_format: str | None) -> dict[str, Any]:
        model = self._model(post, body_format=body_format)
        model["_links"].pop("base")  # a list names the base once, at its end
        return model

    def _comment_model(self, comment: dict[str, Any], body_format: str | None) -> dict[str, Any]:
        post = self.blogposts[comment["blogPostId"]]
        model: dict[str, Any] = {
            "id": comment["id"],
            "status": "current",
            "title": f"Re: {post['title']}",
            "blogPostId": comment["blogPostId"],
            "version": {"number": comment["version"]["number"], "createdAt": comment["version"]["createdAt"], "message": "", "minorEdit": False, "authorId": comment["authorId"]},
            "_links": {"webui": f"{self._links(post)['webui']}#comment-{comment['id']}"},
        }
        if comment["kind"] == "footer":
            model["parentCommentId"] = comment.get("parentCommentId")
        else:
            model["resolutionStatus"] = comment.get("resolutionStatus") or "open"
        if body_format == "storage":
            model["body"] = {"storage": {"representation": "storage", "value": comment["body"]}}
        return model

    # -- the routes ------------------------------------------------------------------------------

    def handle(self, handler: Any, method: str, path: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]], body: Any) -> bool:
        if method == "GET" and path == "/api/v2/blogposts":
            self._list(handler, path, query, query_pairs, space_id=None)
            return True
        if method == "POST" and path == "/api/v2/blogposts":
            self._create(handler, query, body)
            return True
        match = self.match(r"/api/v2/blogposts/([^/]+)", path)
        if match and method == "GET":
            self._get(handler, match.group(1), query)
            return True
        if match and method == "PUT":
            self._update(handler, match.group(1), body)
            return True
        match = self.match(r"/api/v2/spaces/(\d+)/blogposts", path)
        if match and method == "GET":
            self._list(handler, path, query, query_pairs, space_id=match.group(1))
            return True
        match = self.match(r"/api/v2/blogposts/(\d+)/labels", path)
        if match and method == "GET":
            self._labels(handler, path, match.group(1), query, query_pairs)
            return True
        match = self.match(r"/api/v2/blogposts/(\d+)/(footer-comments|inline-comments)", path)
        if match and method == "GET":
            self._comments(handler, path, match.group(1), match.group(2), query, query_pairs)
            return True
        match = self.match(r"/api/v2/(footer-comments|inline-comments)/(\d+)/children", path)
        if match and method == "GET" and match.group(2) in self.comments:
            self._children(handler, path, match.group(1), match.group(2), query, query_pairs)
            return True
        match = self.match(r"/rest/api/content/(\d+)/label", path)
        if match and method == "POST" and match.group(1) in self.blogposts:
            self._add_labels(handler, match.group(1), body)
            return True
        return False

    def _post(self, blogpost_id: str) -> dict[str, Any]:
        if not blogpost_id.isdigit():
            raise RequestError(400, "Invalid request parameter", "Blog post id must be numeric")
        if blogpost_id not in self.blogposts:
            raise RequestError(404, "Not found", f"Blog post not found: {blogpost_id}", code="NOT_FOUND")
        return self.blogposts[blogpost_id]

    def _list(self, handler: Any, path: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]], *, space_id: str | None) -> None:
        allowed = {"sort", "status", "title", "body-format", "cursor", "limit"} | ({"id", "space-id"} if space_id is None else set())
        handler._require_known_query(query, allowed)
        sort = handler._single(query, "sort") or "id"
        if sort not in _SORTS:
            raise RequestError(400, "Invalid request parameter", f"Unsupported value for sort: {sort}")
        statuses = handler._parse_csv_enum(handler._single(query, "status") or "current", "status", _LIST_STATUS)
        body_format = handler._single(query, "body-format")
        if body_format not in {None, *_BODY_FORMATS}:
            raise RequestError(400, "Invalid request parameter", f"Unsupported value for body-format: {body_format}")
        if body_format == "atlas_doc_format":
            raise RequestError(400, "Invalid request parameter", "body-format atlas_doc_format is not implemented by this mock")
        limit = handler._parse_limit(query, default=25)
        offset = handler._parse_cursor(query)
        title = handler._single(query, "title")
        ids = set(handler._parse_csv(handler._single(query, "id"), "id")) or None
        space_ids = set(handler._parse_csv(handler._single(query, "space-id"), "space-id")) or None
        if space_id is not None:
            if space_id not in self.mock.spaces:
                raise RequestError(404, "Not found", f"Space not found: {space_id}", code="NOT_FOUND")
            space_ids = {space_id}
        items = [post for post in self.blogposts.values() if post["status"] in statuses]
        if ids is not None:
            items = [post for post in items if post["id"] in ids]
        if space_ids is not None:
            items = [post for post in items if post["spaceId"] in space_ids]
        if title is not None:
            items = [post for post in items if post["title"].lower() == title.lower()]
        key = sort.lstrip("-")
        order = {"id": lambda post: int(post["id"]), "created-date": lambda post: post["createdAt"], "modified-date": lambda post: post["versions"][-1]["createdAt"]}[key]
        items.sort(key=order, reverse=sort.startswith("-"))
        page_items, links, headers = handler._apply_pagination(items, path=path, query_pairs=query_pairs, offset=offset, limit=limit)
        handler._reply_json(200, {"results": [self._listed(post, body_format) for post in page_items], "_links": links}, headers)

    def _get(self, handler: Any, blogpost_id: str, query: dict[str, list[str]]) -> None:
        handler._require_known_query(
            query,
            {"body-format", "get-draft", "status", "version", "include-labels", "include-properties", "include-operations", "include-likes", "include-versions", "include-version", "include-favorited-by-current-user-status", "include-webresources", "include-collaborators"},
        )
        post = self._post(blogpost_id)
        body_format = handler._single(query, "body-format")
        if body_format not in {None, "storage"}:
            raise RequestError(400, "Invalid request parameter", f"body-format {body_format} is not implemented by this mock")
        statuses = handler._parse_csv_enum(handler._single(query, "status"), "status", _SINGLE_STATUS) if "status" in query else []
        if statuses and post["status"] not in statuses:
            raise RequestError(404, "Not found", f"Blog post not found: {blogpost_id}", code="NOT_FOUND")
        for name in ("get-draft", "include-labels", "include-properties", "include-operations", "include-likes", "include-versions", "include-favorited-by-current-user-status", "include-webresources", "include-collaborators"):
            handler._parse_bool(handler._single(query, name), name)
        include_version = handler._parse_bool(handler._single(query, "include-version"), "include-version")
        version_number = handler._parse_int_query(handler._single(query, "version"), "version")
        if version_number is not None and version_number not in {item["number"] for item in post["versions"]}:
            raise RequestError(404, "Not found", f"Version not found: {version_number}", code="NOT_FOUND")
        handler._reply_json(200, self._model(post, body_format=body_format, version_number=version_number, include_version=include_version is not False))

    def _create(self, handler: Any, query: dict[str, list[str]], body: Any) -> None:
        handler._require_known_query(query, {"private"})
        handler._parse_bool(handler._single(query, "private"), "private")
        data = handler._require_object(body)
        space_id = data.get("spaceId")
        if not isinstance(space_id, str):
            raise RequestError(400, "Invalid request body", "spaceId is required and must be a string")
        if space_id not in self.mock.spaces:
            raise RequestError(400, "Invalid request body", f"Unknown spaceId: {space_id}")
        status = data.get("status", "current")
        if status not in {"current", "draft"}:
            raise RequestError(400, "Invalid request body", f"Unsupported status: {status}")
        title = data.get("title")
        if status != "draft" and not (isinstance(title, str) and title.strip()):
            raise RequestError(400, "Invalid request body", "title is required unless status is draft")
        if title is not None and not isinstance(title, str):
            raise RequestError(400, "Invalid request body", "title must be a string")
        value = handler._parse_body_value(data.get("body")) or ""
        blogpost_id = str(self.mock._next_page)
        self.mock._next_page += 1
        created = self.mock._tick()
        self.blogposts[blogpost_id] = {
            "id": blogpost_id,
            "spaceId": space_id,
            "title": title if title is not None else "Untitled draft",
            "status": status,
            "authorId": self.account,
            "createdAt": created,
            "versions": [{"number": 1, "createdAt": created, "message": "Created", "minorEdit": False, "authorId": self.account, "body": value}],
            "labels": [],
        }
        self.mock.content_kinds[blogpost_id] = "blogpost"
        handler._reply_json(200, self._model(self.blogposts[blogpost_id], body_format="storage"))

    def _update(self, handler: Any, blogpost_id: str, body: Any) -> None:
        post = self._post(blogpost_id)
        data = handler._require_object(body)
        for required in ("id", "status", "title", "body", "version"):
            if required not in data:
                raise RequestError(400, "Invalid request body", f"{required} is required")
        if data["id"] != blogpost_id:
            raise RequestError(400, "Invalid request body", "Body id must match the path id")
        if data["status"] != "current":
            raise RequestError(400, "Invalid request body", f"Unsupported status: {data['status']} (this mock keeps blog posts current)")
        if not isinstance(data["title"], str) or not data["title"].strip():
            raise RequestError(400, "Invalid request body", "title must be a non-empty string")
        version = data["version"]
        if not isinstance(version, dict) or not isinstance(version.get("number"), int):
            raise RequestError(400, "Invalid request body", "version.number is required")
        if "spaceId" in data and data["spaceId"] != post["spaceId"]:
            raise RequestError(400, "Invalid request body", "spaceId cannot change")
        current = post["versions"][-1]["number"]
        if version["number"] != current + 1:
            raise RequestError(409, "Version conflict", f"Expected version.number {current + 1} but got {version['number']}", code="CONFLICT")
        value = handler._parse_body_value(data["body"]) or ""
        post["title"] = data["title"]
        post["versions"].append(
            {"number": version["number"], "createdAt": self.mock._tick(), "message": version.get("message", ""), "minorEdit": False, "authorId": self.account, "body": value}
        )
        handler._reply_json(200, self._model(post, body_format="storage"))

    def _labels(self, handler: Any, path: str, blogpost_id: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]]) -> None:
        handler._require_known_query(query, {"prefix", "sort", "cursor", "limit"})
        post = self._post(blogpost_id)
        prefix = handler._single(query, "prefix")
        if prefix not in {None, "my", "team", "global", "system"}:
            raise RequestError(400, "Invalid request parameter", f"Unsupported value for prefix: {prefix}")
        sort = handler._single(query, "sort") or "name"
        if sort not in {"name", "-name"}:
            raise RequestError(400, "Invalid request parameter", f"Unsupported value for sort: {sort}")
        limit = handler._parse_limit(query, default=25)
        offset = handler._parse_cursor(query)
        names = sorted(post["labels"], reverse=sort.startswith("-"))
        items = [{"id": f"lbl-{blogpost_id}-{name}", "name": name, "prefix": "global"} for name in names if prefix in {None, "global"}]
        page_items, links, headers = handler._apply_pagination(items, path=path, query_pairs=query_pairs, offset=offset, limit=limit)
        handler._reply_json(200, {"results": page_items, "_links": links}, headers)

    def _comments(self, handler: Any, path: str, blogpost_id: str, collection: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]]) -> None:
        allowed = {"body-format", "status", "sort", "cursor", "limit"} | ({"resolution-status"} if collection == "inline-comments" else set())
        handler._require_known_query(query, allowed)
        self._post(blogpost_id)
        body_format = handler._single(query, "body-format")
        if body_format not in {None, *_BODY_FORMATS}:
            raise RequestError(400, "Invalid request parameter", f"Unsupported value for body-format: {body_format}")
        if body_format == "atlas_doc_format":
            raise RequestError(400, "Invalid request parameter", "body-format atlas_doc_format is not implemented by this mock")
        handler._parse_csv_enum(handler._single(query, "status") or "current", "status", _COMMENT_STATUS)
        sort = handler._single(query, "sort") or "created-date"
        if sort not in _COMMENT_SORTS:
            raise RequestError(400, "Invalid request parameter", f"Unsupported value for sort: {sort}")
        limit = handler._parse_limit(query, default=25)
        offset = handler._parse_cursor(query)
        kind = "footer" if collection == "footer-comments" else "inline"
        items = [comment for comment in self.comments.values() if comment["blogPostId"] == blogpost_id and comment["kind"] == kind and not comment.get("parentCommentId")]
        items.sort(key=lambda comment: comment["version"]["createdAt"], reverse=sort.startswith("-"))
        models = [self._comment_model(comment, body_format) for comment in items]
        page_items, links, headers = handler._apply_pagination(models, path=path, query_pairs=query_pairs, offset=offset, limit=limit)
        handler._reply_json(200, {"results": page_items, "_links": links}, headers)

    def _children(self, handler: Any, path: str, collection: str, comment_id: str, query: dict[str, list[str]], query_pairs: list[tuple[str, str]]) -> None:
        handler._require_known_query(query, {"body-format", "sort", "cursor", "limit"})
        kind = "footer" if collection == "footer-comments" else "inline"
        if self.comments[comment_id]["kind"] != kind:
            raise RequestError(404, "Not found", f"Comment not found: {comment_id}", code="NOT_FOUND")
        body_format = handler._single(query, "body-format")
        if body_format not in {None, *_BODY_FORMATS}:
            raise RequestError(400, "Invalid request parameter", f"Unsupported value for body-format: {body_format}")
        sort = handler._single(query, "sort") or "created-date"
        if sort not in _COMMENT_SORTS:
            raise RequestError(400, "Invalid request parameter", f"Unsupported value for sort: {sort}")
        limit = handler._parse_limit(query, default=25)
        offset = handler._parse_cursor(query)
        items = [comment for comment in self.comments.values() if comment.get("parentCommentId") == comment_id and comment["kind"] == kind]
        items.sort(key=lambda comment: comment["version"]["createdAt"], reverse=sort.startswith("-"))
        models = [self._comment_model(comment, body_format) for comment in items]
        page_items, links, headers = handler._apply_pagination(models, path=path, query_pairs=query_pairs, offset=offset, limit=limit)
        handler._reply_json(200, {"results": page_items, "_links": links}, headers)

    def _add_labels(self, handler: Any, blogpost_id: str, body: Any) -> None:
        entries = body if isinstance(body, list) else [body]
        if not entries or any(not isinstance(item, dict) for item in entries):
            raise RequestError(400, "Bad Request", "Invalid label payload", old=True, old_key="BAD_REQUEST")
        labels = self.blogposts[blogpost_id]["labels"]
        for entry in entries:
            if entry.get("prefix") != "global" or not isinstance(entry.get("name"), str):
                raise RequestError(400, "Bad Request", "prefix and name are required", old=True, old_key="BAD_REQUEST")
            name = entry["name"].lower()
            if any(char in _FORBIDDEN_LABEL_CHARS for char in name):
                raise RequestError(400, "Bad Request", f"Invalid label name: {entry['name']}", old=True, old_key="BAD_REQUEST")
            if name not in labels:
                labels.append(name)
        labels.sort()
        handler._reply_json(200, {"results": [{"id": f"lbl-{blogpost_id}-{name}", "name": name, "prefix": "global"} for name in labels], "start": 0, "limit": 200, "size": len(labels)})
