from __future__ import annotations

import base64
import gzip
import http.client
import json
import unittest
from urllib.parse import parse_qs, urlencode, urlsplit

from tests.support.mock_confluence import MockConfluence


class _Client:
    def __init__(self, mock: MockConfluence, *, auth: bool = True) -> None:
        self.mock = mock
        self.auth = auth

    def _headers(self, headers: dict[str, str] | None = None) -> dict[str, str]:
        merged = dict(headers or {})
        if self.auth:
            token = base64.b64encode(f"{self.mock.email}:{self.mock.token}".encode("utf-8")).decode("ascii")
            merged.setdefault("Authorization", f"Basic {token}")
        return merged

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, object] | None = None,
        json_body: object | None = None,
        raw_body: bytes | None = None,
        headers: dict[str, str] | None = None,
        absolute: bool = False,
    ) -> tuple[int, dict[str, str], object]:
        split = urlsplit(self.mock.base_url)
        target = path if absolute else f"{self.mock.context_path}{path}"
        if query:
            pairs: list[tuple[str, str]] = []
            for key, value in query.items():
                if isinstance(value, (list, tuple)):
                    pairs.extend((key, str(item)) for item in value)
                else:
                    pairs.append((key, str(value)))
            target = f"{target}?{urlencode(pairs)}"
        body = None
        request_headers = self._headers(headers)
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        elif raw_body is not None:
            body = raw_body
        connection = http.client.HTTPConnection(split.hostname, split.port)
        try:
            connection.request(method, target, body=body, headers=request_headers)
            response = connection.getresponse()
            raw = response.read()
            response_headers = {key.lower(): value for key, value in response.getheaders()}
            if response_headers.get("content-encoding") == "gzip":
                raw = gzip.decompress(raw)
            if response_headers.get("content-type", "").startswith("application/json") and raw:
                return response.status, response_headers, json.loads(raw.decode("utf-8"))
            return response.status, response_headers, raw
        finally:
            connection.close()

    def request_connection(
        self,
        connection: http.client.HTTPConnection,
        method: str,
        path: str,
        *,
        query: dict[str, object] | None = None,
        json_body: object | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], object]:
        target = f"{self.mock.context_path}{path}"
        if query:
            target = f"{target}?{urlencode([(key, str(value)) for key, value in query.items()])}"
        body = None
        request_headers = self._headers(headers)
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        connection.request(method, target, body=body, headers=request_headers)
        response = connection.getresponse()
        raw = response.read()
        response_headers = {key.lower(): value for key, value in response.getheaders()}
        if response_headers.get("content-type", "").startswith("application/json") and raw:
            return response.status, response_headers, json.loads(raw.decode("utf-8"))
        return response.status, response_headers, raw

    def follow_next(self, next_path: str) -> tuple[int, dict[str, str], object]:
        return self.request("GET", next_path.removeprefix(self.mock.context_path), absolute=False)

    @staticmethod
    def multipart(file_name: str, data: bytes, *, media_type: str = "application/octet-stream", fields: dict[str, str] | None = None) -> tuple[bytes, dict[str, str]]:
        boundary = "mock-boundary"
        chunks = []
        for name, value in (fields or {}).items():
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode("utf-8"),
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                    value.encode("utf-8"),
                    b"\r\n",
                ]
            )
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n'.encode("utf-8"),
                f"Content-Type: {media_type}\r\n\r\n".encode("utf-8"),
                data,
                b"\r\n",
                f"--{boundary}--\r\n".encode("utf-8"),
            ]
        )
        return b"".join(chunks), {"Content-Type": f"multipart/form-data; boundary={boundary}"}


class _BaseCase(unittest.TestCase):
    def setUp(self) -> None:
        self.mock = MockConfluence(page_cap=2)
        self.mock.start()
        self.addCleanup(self.mock.stop)
        self.client = _Client(self.mock)


class TestDatasetAndAuth(_BaseCase):
    def test_base_urls_and_current_user(self) -> None:
        self.assertTrue(self.mock.base_url.startswith("http://127.0.0.1:"))
        self.assertTrue(self.mock.base_url.endswith("/wiki"))
        self.assertTrue(self.mock.media_url.startswith("http://127.0.0.1:"))
        status, _, payload = self.client.request("GET", "/rest/api/user/current")
        self.assertEqual(status, 200)
        self.assertEqual(payload["accountId"], "5b10ac8d82e05b22cc7d4ef5")
        self.assertEqual(payload["displayName"], "Alex Example")
        self.assertEqual(payload["email"], "alex@example.com")

    def test_default_dataset_exact_values(self) -> None:
        self.assertEqual(set(self.mock.spaces), {"1001", "1002"})
        self.assertEqual(self.mock.spaces["1001"]["description"], "Engineering documentation")
        self.assertEqual(self.mock.pages["2002"]["labels"], ["release", "notes"])
        self.assertEqual(self.mock.pages["2002"]["versions"][-1]["message"], "Added the October notes")
        self.assertEqual(
            self.mock.pages["2002"]["versions"][-1]["body"],
            '<h1>Release notes</h1><p>Contact <ac:link><ri:user ri:account-id="5b10ac8d82e05b22cc7d4ef5" /></ac:link> or write to alex@example.com.</p><ul><li>First</li><li>Second</li></ul><ac:structured-macro ac:name="toc" ac:schema-version="1" />',
        )
        self.assertEqual(self.mock.comments["4003"]["resolutionStatus"], "open")
        self.assertEqual(self.mock.attachments["att5001"]["versions"][-1]["data"], b"PNGDATA123")

    def test_auth_missing_is_401_v2(self) -> None:
        status, _, payload = _Client(self.mock, auth=False).request("GET", "/api/v2/pages")
        self.assertEqual(status, 401)
        self.assertEqual(payload["statusCode"], 401)

    def test_auth_wrong_is_401_old(self) -> None:
        status, _, payload = _Client(self.mock, auth=False).request("GET", "/rest/api/search", query={"cql": 'space = "ENG"'}, headers={"Authorization": "Basic nope"})
        self.assertEqual(status, 401)
        self.assertEqual(payload["data"]["authorized"], False)

    def test_populate_false_starts_empty(self) -> None:
        with MockConfluence(populate=False) as mock:
            self.assertEqual(mock.spaces, {})
            self.assertEqual(mock.pages, {})
            self.assertEqual(mock.comments, {})
            self.assertEqual(mock.attachments, {})
            status, _, payload = _Client(mock).request("GET", "/rest/api/user/current")
            self.assertEqual(status, 200)
            self.assertEqual(payload["accountId"], "5b10ac8d82e05b22cc7d4ef5")

    def test_unknown_path_is_404_json(self) -> None:
        status, _, payload = self.client.request("GET", "/api/v2/nope")
        self.assertEqual(status, 404)
        self.assertEqual(payload["errors"][0]["code"], "NOT_FOUND")


class TestPaginationAndStrictness(_BaseCase):
    def _collect(self, path: str, *, query: dict[str, object] | None = None) -> list[dict]:
        status, headers, payload = self.client.request("GET", path, query=query)
        self.assertEqual(status, 200)
        items = list(payload["results"])
        while "_links" in payload and "next" in payload["_links"]:
            self.assertIn("link", headers)
            status, headers, payload = self.client.follow_next(payload["_links"]["next"])
            self.assertEqual(status, 200)
            items.extend(payload["results"])
        return items

    def test_pages_pagination_follow_next(self) -> None:
        items = self._collect("/api/v2/pages", query={"sort": "id"})
        self.assertEqual([item["id"] for item in items], ["2001", "2002", "2003", "2004", "2005", "3001"])

    def test_spaces_pagination_follow_next(self) -> None:
        items = self._collect("/api/v2/spaces", query={"sort": "id"})
        self.assertEqual([item["id"] for item in items], ["1001", "1002"])

    def test_descendants_pagination_follow_next(self) -> None:
        for title in ("Child A", "Child B", "Child C"):
            self.mock.add_page("ENG", title, parent_id="2003")
        items = self._collect("/api/v2/pages/2001/descendants", query={"depth": 3})
        self.assertEqual(len({item["id"] for item in items}), len(items))
        self.assertIn("2004", [item["id"] for item in items])

    def test_unknown_query_parameter_is_400(self) -> None:
        status, _, payload = self.client.request("GET", "/api/v2/pages", query={"bogus": "1"})
        self.assertEqual(status, 400)
        self.assertIn("Unknown query parameter", payload["errors"][0]["detail"])

    def test_bad_enum_is_400(self) -> None:
        status, _, payload = self.client.request("GET", "/api/v2/spaces", query={"status": "invalid"})
        self.assertEqual(status, 400)
        self.assertIn("Unsupported value for status", payload["errors"][0]["detail"])

    def test_bad_limit_is_400(self) -> None:
        status, _, payload = self.client.request("GET", "/api/v2/pages", query={"limit": 251})
        self.assertEqual(status, 400)
        self.assertIn("limit must be between 1 and 250", payload["errors"][0]["detail"])

    def test_bad_cursor_is_400(self) -> None:
        status, _, payload = self.client.request("GET", "/api/v2/pages", query={"cursor": "abc"})
        self.assertEqual(status, 400)
        self.assertIn("cursor must be a numeric offset", payload["errors"][0]["detail"])

    def test_keep_other_query_params_in_next_link(self) -> None:
        status, _, payload = self.client.request("GET", "/api/v2/pages", query={"space-id": "1001", "limit": 1, "sort": "id"})
        self.assertEqual(status, 200)
        next_link = payload["_links"]["next"]
        self.assertIn("/wiki/api/v2/pages?", next_link)
        parsed = parse_qs(urlsplit(next_link).query)
        self.assertEqual(parsed["space-id"], ["1001"])
        self.assertEqual(parsed["limit"], ["1"])
        self.assertEqual(parsed["sort"], ["id"])
        self.assertEqual(parsed["cursor"], ["1"])


class TestPagesAndComments(_BaseCase):
    def test_get_pages_filter_and_body(self) -> None:
        status, _, payload = self.client.request("GET", "/api/v2/pages", query={"space-id": "1001", "title": "Release notes", "body-format": "storage"})
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["results"][0]["body"]["storage"]["value"], self.mock.pages["2002"]["versions"][-1]["body"])

    def test_get_page_include_labels(self) -> None:
        status, _, payload = self.client.request("GET", "/api/v2/pages/2002", query={"include-labels": "true", "body-format": "storage"})
        self.assertEqual(status, 200)
        self.assertEqual([item["name"] for item in payload["labels"]["results"]], ["release", "notes"])

    def test_get_page_bad_id(self) -> None:
        status, _, payload = self.client.request("GET", "/api/v2/pages/not-a-number")
        self.assertEqual(status, 400)
        self.assertIn("must be numeric", payload["errors"][0]["detail"])

    def test_get_page_unsupported_body_format(self) -> None:
        status, _, payload = self.client.request("GET", "/api/v2/pages/2002", query={"body-format": "view"})
        self.assertEqual(status, 400)
        self.assertIn("not implemented", payload["errors"][0]["detail"])

    def test_create_page_defaults_to_home_parent(self) -> None:
        status, _, payload = self.client.request("POST", "/api/v2/pages", json_body={"spaceId": "1001", "title": "New page", "status": "current", "body": {"representation": "storage", "value": "<p>x</p>"}})
        self.assertEqual(status, 200)
        self.assertEqual(payload["parentId"], "2001")
        self.assertEqual(self.mock.pages[payload["id"]]["parentId"], "2001")
        self.assertEqual(payload["version"]["number"], 1)

    def test_create_page_title_conflict(self) -> None:
        status, _, payload = self.client.request("POST", "/api/v2/pages", json_body={"spaceId": "1001", "title": "Release notes", "status": "current"})
        self.assertEqual(status, 400)
        self.assertEqual(payload["errors"][0]["title"], "A page with this title already exists")

    def test_create_page_parent_other_space(self) -> None:
        status, _, payload = self.client.request("POST", "/api/v2/pages", json_body={"spaceId": "1001", "title": "Cross", "status": "current", "parentId": "3001"})
        self.assertEqual(status, 400)
        self.assertIn("same space", payload["errors"][0]["detail"])

    def test_create_page_unknown_space(self) -> None:
        status, _, payload = self.client.request("POST", "/api/v2/pages", json_body={"spaceId": "9999", "title": "Nope", "status": "current"})
        self.assertEqual(status, 400)
        self.assertIn("Unknown spaceId", payload["errors"][0]["detail"])

    def test_update_page_success(self) -> None:
        status, _, payload = self.client.request(
            "PUT",
            "/api/v2/pages/2005",
            json_body={
                "id": "2005",
                "status": "current",
                "title": "Plain page updated",
                "body": {"storage": {"representation": "storage", "value": "<p>Updated</p>"}},
                "version": {"number": 2, "message": "edit"},
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["version"]["number"], 2)
        self.assertEqual(self.mock.pages["2005"]["versions"][-1]["body"], "<p>Updated</p>")

    def test_update_page_version_conflict(self) -> None:
        status, _, payload = self.client.request(
            "PUT",
            "/api/v2/pages/2005",
            json_body={"id": "2005", "status": "current", "title": "Plain page", "body": {"representation": "storage", "value": "<p>x</p>"}, "version": {"number": 5}},
        )
        self.assertEqual(status, 409)
        self.assertEqual(payload["errors"][0]["code"], "CONFLICT")

    def test_update_page_title_conflict(self) -> None:
        status, _, payload = self.client.request(
            "PUT",
            "/api/v2/pages/2005",
            json_body={"id": "2005", "status": "current", "title": "Release notes", "body": {"representation": "storage", "value": "<p>x</p>"}, "version": {"number": 2}},
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["errors"][0]["title"], "A page with this title already exists")

    def test_put_title_adds_version_without_body(self) -> None:
        status, _, payload = self.client.request("PUT", "/api/v2/pages/2005/title", json_body={"status": "current", "title": "Renamed plain page"})
        self.assertEqual(status, 200)
        self.assertNotIn("body", payload)
        self.assertEqual(self.mock.pages["2005"]["versions"][-1]["number"], 2)

    def test_get_ancestors(self) -> None:
        status, _, payload = self.client.request("GET", "/api/v2/pages/2004/ancestors")
        self.assertEqual(status, 200)
        self.assertEqual(payload["results"], [{"id": "2001", "type": "page"}, {"id": "2003", "type": "page"}])

    def test_get_versions_default_newest_first(self) -> None:
        status, _, payload = self.client.request("GET", "/api/v2/pages/2002/versions")
        self.assertEqual(status, 200)
        self.assertEqual([item["number"] for item in payload["results"]], [3, 2])

    def test_move_append(self) -> None:
        status, _, payload = self.client.request("PUT", "/rest/api/content/2005/move/append/2003")
        self.assertEqual(status, 200)
        self.assertEqual(payload["id"], "2005")
        self.assertEqual(self.mock.pages["2005"]["parentId"], "2003")

    def test_move_before_after(self) -> None:
        self.client.request("PUT", "/rest/api/content/2005/move/before/2002")
        self.assertEqual([page["id"] for page in self.mock._children("2001")], ["2005", "2002", "2003"])
        self.client.request("PUT", "/rest/api/content/2005/move/after/2003")
        self.assertEqual([page["id"] for page in self.mock._children("2001")], ["2002", "2003", "2005"])

    def test_move_below_descendant_rejected(self) -> None:
        status, _, payload = self.client.request("PUT", "/rest/api/content/2003/move/append/2004")
        self.assertEqual(status, 400)
        self.assertIn("descendants", payload["message"])

    def test_footer_comments_roots_only(self) -> None:
        status, _, payload = self.client.request("GET", "/api/v2/pages/2002/footer-comments", query={"body-format": "storage"})
        self.assertEqual(status, 200)
        self.assertEqual([item["id"] for item in payload["results"]], ["4001"])

    def test_comment_children_endpoint(self) -> None:
        status, _, payload = self.client.request("GET", "/api/v2/footer-comments/4001/children", query={"body-format": "storage"})
        self.assertEqual(status, 200)
        self.assertEqual([item["id"] for item in payload["results"]], ["4002"])

    def test_inline_comments_resolution_status(self) -> None:
        status, _, payload = self.client.request("GET", "/api/v2/pages/2002/inline-comments", query={"body-format": "storage", "resolution-status": "open"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["results"][0]["resolutionStatus"], "open")

    def test_post_footer_comment_root(self) -> None:
        status, _, payload = self.client.request("POST", "/api/v2/footer-comments", json_body={"pageId": "2002", "body": {"representation": "storage", "value": "<p>New root</p>"}})
        self.assertEqual(status, 201)
        self.assertEqual(payload["pageId"], "2002")
        self.assertIn(payload["id"], self.mock.comments)

    def test_post_footer_reply(self) -> None:
        # the document: a reply names its parent comment and not the page ("Do not provide" it); the reply is on the page of its parent
        status, _, payload = self.client.request("POST", "/api/v2/footer-comments", json_body={"parentCommentId": "4001", "body": {"representation": "storage", "value": "<p>Reply</p>"}})
        self.assertEqual(status, 201)
        self.assertEqual(self.mock.comments[payload["id"]]["parentCommentId"], "4001")
        self.assertEqual(payload["pageId"], "2002")

    def test_post_footer_reply_with_a_page_is_refused(self) -> None:
        status, _, payload = self.client.request("POST", "/api/v2/footer-comments", json_body={"pageId": "2002", "parentCommentId": "4001", "body": {"representation": "storage", "value": "<p>Reply</p>"}})
        self.assertEqual(status, 400)
        self.assertIn("Do not provide pageId", payload["errors"][0]["detail"])

    def test_post_footer_comment_unknown_page(self) -> None:
        status, _, payload = self.client.request("POST", "/api/v2/footer-comments", json_body={"pageId": "9999", "body": {"representation": "storage", "value": "<p>x</p>"}})
        self.assertEqual(status, 404)
        self.assertEqual(payload["errors"][0]["code"], "NOT_FOUND")

    def test_post_footer_comment_unknown_parent(self) -> None:
        status, _, payload = self.client.request("POST", "/api/v2/footer-comments", json_body={"parentCommentId": "4999", "body": {"representation": "storage", "value": "<p>x</p>"}})
        self.assertEqual(status, 400)
        self.assertIn("parentCommentId", payload["errors"][0]["detail"])


class TestSearchLabelsAndAttachments(_BaseCase):
    def test_add_labels_lowercase_and_dedupe(self) -> None:
        status, _, payload = self.client.request("POST", "/rest/api/content/2005/label", json_body=[{"prefix": "global", "name": "Foo"}, {"prefix": "global", "name": "foo"}])
        self.assertEqual(status, 200)
        self.assertEqual([item["name"] for item in payload["results"]], ["foo"])

    def test_delete_label(self) -> None:
        self.client.request("POST", "/rest/api/content/2005/label", json_body={"prefix": "global", "name": "temp"})
        status, _, payload = self.client.request("DELETE", "/rest/api/content/2005/label/temp")
        self.assertEqual(status, 204)
        self.assertEqual(payload, b"")

    def test_invalid_label_name(self) -> None:
        status, _, payload = self.client.request("POST", "/rest/api/content/2005/label", json_body={"prefix": "global", "name": "bad name"})
        self.assertEqual(status, 400)
        self.assertIn("Invalid label name", payload["message"])

    def test_search_text_space_and_label(self) -> None:
        status, _, payload = self.client.request("GET", "/rest/api/search", query={"cql": 'space = "ENG" AND label = "release" AND text ~ "Second alex@example.com"'})
        self.assertEqual(status, 200)
        self.assertEqual([item["content"]["id"] for item in payload["results"]], ["2002"])
        self.assertIn("@@@hl@@@", payload["results"][0]["excerpt"])

    def test_search_ancestor_lastmodified_and_order(self) -> None:
        status, _, payload = self.client.request("GET", "/rest/api/search", query={"cql": 'ancestor = 2001 AND lastmodified >= "2026-10-05" ORDER BY lastmodified ASC'})
        self.assertEqual(status, 200)
        self.assertEqual([item["content"]["id"] for item in payload["results"]], ["2004", "2002"])

    def test_search_any_group_phrase_and_wildcard(self) -> None:
        def ids(cql: str) -> list[str]:
            status, _, payload = self.client.request("GET", "/rest/api/search", query={"cql": cql})
            self.assertEqual(status, 200, payload)
            return [item["content"]["id"] for item in payload["results"]]

        self.mock.page_cap = 10
        self.assertEqual(sorted(ids('type = page AND (text ~ "release" OR text ~ "decision")')), ["2002", "2004"])
        self.assertEqual(ids('type = page AND text ~ "\\"just a paragraph\\""'), ["2005"])
        self.assertEqual(ids('type = page AND text ~ "\\"paragraph just\\""'), [])
        self.assertEqual(ids('type = page AND text ~ "adapt*"'), ["2004"])
        self.assertEqual(ids('type = page AND text ~ "decision" AND text ~ "ports"'), ["2004"])

    def test_search_expand_adds_ancestors_labels_and_version(self) -> None:
        status, _, payload = self.client.request("GET", "/rest/api/search", query={"cql": 'type = page AND text ~ "ports"', "expand": "content.ancestors,content.metadata.labels,content.version"})
        self.assertEqual(status, 200)
        content = payload["results"][0]["content"]
        self.assertEqual([item["title"] for item in content["ancestors"]], ["Engineering Home", "Architecture"])
        self.assertEqual([item["name"] for item in content["metadata"]["labels"]["results"]], ["adr"])
        self.assertEqual(content["version"]["number"], 2)
        status, _, plain = self.client.request("GET", "/rest/api/search", query={"cql": 'type = page AND text ~ "ports"'})
        self.assertEqual(set(plain["results"][0]["content"]), {"id", "type", "status", "title", "_links"})  # nothing unasked for

    def test_search_refuses_an_expand_it_does_not_know_and_a_broken_group(self) -> None:
        status, _, payload = self.client.request("GET", "/rest/api/search", query={"cql": "type = page", "expand": "content.nonsense"})
        self.assertEqual(status, 400)
        self.assertIn("Unsupported value for expand", payload["message"])
        for cql in ('(text ~ "a" OR )', '(text ~ "a" OR text ~ "b"', 'text ~ "a" OR text ~ "b"'):
            status, _, payload = self.client.request("GET", "/rest/api/search", query={"cql": cql})
            self.assertEqual(status, 400, cql)

    def test_search_parse_error(self) -> None:
        status, _, payload = self.client.request("GET", "/rest/api/search", query={"cql": 'space = ENG'})
        self.assertEqual(status, 400)
        self.assertIn("Could not parse cql", payload["message"])

    def test_attachment_list_and_single(self) -> None:
        status, _, payload = self.client.request("GET", "/api/v2/pages/2002/attachments", query={"filename": "diagram.png"})
        self.assertEqual(status, 200)
        self.assertEqual([item["id"] for item in payload["results"]], ["att5001"])
        status, _, payload = self.client.request("GET", "/api/v2/attachments/att5002")
        self.assertEqual(status, 200)
        self.assertEqual(payload["mediaType"], "text/plain")

    def test_upload_attachment_post_new(self) -> None:
        body, headers = _Client.multipart("new.txt", b"hello", media_type="text/plain", fields={"comment": "added"})
        status, _, payload = self.client.request("POST", "/rest/api/content/2002/child/attachment", raw_body=body, headers={**headers, "X-Atlassian-Token": "nocheck"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["results"][0]["title"], "new.txt")
        self.assertEqual(self.mock.attachments[payload["results"][0]["id"]]["versions"][-1]["data"], b"hello")

    def test_upload_attachment_put_new_version(self) -> None:
        body, headers = _Client.multipart("notes.txt", b"changed", media_type="text/plain", fields={"comment": "v2"})
        status, _, payload = self.client.request("PUT", "/rest/api/content/2002/child/attachment", raw_body=body, headers={**headers, "X-Atlassian-Token": "nocheck"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["results"][0]["version"]["number"], 2)
        self.assertEqual(self.mock.attachments["att5002"]["versions"][-1]["data"], b"changed")

    def test_upload_attachment_xsrf_required(self) -> None:
        body, headers = _Client.multipart("new.txt", b"hello")
        status, _, payload = self.client.request("POST", "/rest/api/content/2002/child/attachment", raw_body=body, headers=headers)
        self.assertEqual(status, 403)
        self.assertEqual(payload["message"], "XSRF check failed")

    def test_upload_attachment_post_duplicate_rejected(self) -> None:
        body, headers = _Client.multipart("notes.txt", b"hello")
        status, _, payload = self.client.request("POST", "/rest/api/content/2002/child/attachment", raw_body=body, headers={**headers, "X-Atlassian-Token": "nocheck"})
        self.assertEqual(status, 400)
        self.assertIn("Cannot add a new attachment", payload["message"])

    def test_download_redirect_and_media_without_auth(self) -> None:
        status, headers, _ = self.client.request("GET", "/download/attachments/2002/diagram.png")
        self.assertEqual(status, 302)
        location = headers["location"]
        split = urlsplit(location)
        conn = http.client.HTTPConnection(split.hostname, split.port)
        try:
            conn.request("GET", f"{split.path}?{split.query}")
            response = conn.getresponse()
            data = response.read()
        finally:
            conn.close()
        self.assertEqual(response.status, 200)
        self.assertEqual(data, b"PNGDATA123")
        self.assertNotIn("authorization", self.mock.media_requests[-1].headers)

    def test_media_wrong_token_forbidden(self) -> None:
        status, headers, _ = self.client.request("GET", "/download/attachments/2002/diagram.png")
        split = urlsplit(headers["location"])
        bad_query = parse_qs(split.query)
        bad_query["token"] = ["wrong"]
        target = f"{split.path}?{urlencode([(key, value[0]) for key, value in bad_query.items()])}"
        conn = http.client.HTTPConnection(split.hostname, split.port)
        try:
            conn.request("GET", target)
            response = conn.getresponse()
            data = response.read()
        finally:
            conn.close()
        self.assertEqual(response.status, 403)
        self.assertEqual(data, b"forbidden")

    def test_users_bulk_requires_string_ids(self) -> None:
        status, _, payload = self.client.request("POST", "/api/v2/users-bulk", json_body={"accountIds": [123]})
        self.assertEqual(status, 400)
        self.assertIn("accountIds", payload["errors"][0]["detail"])


class TestFailureGzipKeepAliveAndHelpers(_BaseCase):
    def test_fail_next_status_times_and_headers(self) -> None:
        self.mock.fail_next("/api/v2/pages/2002", 503, times=2, headers={"Retry-After": "7"})
        first = self.client.request("GET", "/api/v2/pages/2002")
        second = self.client.request("GET", "/api/v2/pages/2002")
        third = self.client.request("GET", "/api/v2/pages/2002")
        self.assertEqual(first[0], 503)
        self.assertEqual(first[1]["retry-after"], "7")
        self.assertEqual(second[0], 503)
        self.assertEqual(third[0], 200)

    def test_fail_next_method_filter(self) -> None:
        self.mock.fail_next("/api/v2/pages", 502, method="POST")
        self.assertEqual(self.client.request("GET", "/api/v2/pages")[0], 200)
        self.assertEqual(self.client.request("POST", "/api/v2/pages", json_body={"spaceId": "1001", "title": "Injected", "status": "current"})[0], 502)

    def test_gzip_response(self) -> None:
        self.mock.gzip = True
        status, headers, payload = self.client.request("GET", "/api/v2/pages/2002", query={"body-format": "storage"}, headers={"Accept-Encoding": "gzip"})
        self.assertEqual(status, 200)
        self.assertEqual(headers["content-encoding"], "gzip")
        self.assertEqual(payload["id"], "2002")

    def test_keep_alive_two_requests_one_connection(self) -> None:
        split = urlsplit(self.mock.base_url)
        connection = http.client.HTTPConnection(split.hostname, split.port)
        try:
            first = self.client.request_connection(connection, "GET", "/api/v2/pages")
            second = self.client.request_connection(connection, "GET", "/api/v2/spaces")
        finally:
            connection.close()
        self.assertEqual(first[0], 200)
        self.assertEqual(second[0], 200)
        self.assertGreaterEqual(len(self.mock.requests), 2)

    def test_helper_methods_add_objects(self) -> None:
        space_id = self.mock.add_space("OPS", "Operations")
        page_id = self.mock.add_page("OPS", "Runbook", "<p>R</p>")
        comment_id = self.mock.add_comment(page_id, "<p>C</p>")
        attachment_id = self.mock.add_attachment(page_id, "runbook.txt", b"rb", "text/plain")
        self.assertEqual(self.mock.spaces[space_id]["key"], "OPS")
        self.assertEqual(self.mock.pages[page_id]["parentId"], self.mock.spaces[space_id]["homepageId"])
        self.assertEqual(self.mock.comments[comment_id]["pageId"], page_id)
        self.assertEqual(self.mock.attachments[attachment_id]["title"], "runbook.txt")

    def test_requests_record_rejected_and_raw(self) -> None:
        status, _, _ = _Client(self.mock, auth=False).request("GET", "/api/v2/pages")
        self.assertEqual(status, 401)
        self.assertEqual(self.mock.requests[-1].target, "GET /api/v2/pages")
        self.assertEqual(self.mock.requests[-1].headers.get("authorization"), None)

    def test_invalid_json_body_is_400(self) -> None:
        status, _, payload = self.client.request("POST", "/api/v2/pages", raw_body=b"{", headers={"Content-Type": "application/json"})
        self.assertEqual(status, 400)
        self.assertEqual(self.mock.requests[-1].raw, b"{")
        self.assertIn("Invalid JSON body", payload["errors"][0]["detail"])
