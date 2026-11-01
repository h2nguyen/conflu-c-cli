"""Watching a page or a space, the rules and the calls: what a change is, the REST call it sends, and how the adapter addresses and reads it."""
import dataclasses
import unittest

from conflu_c_cli.adapters.driven import map_watches
from conflu_c_cli.adapters.driven.http_transport import HttpResponse
from conflu_c_cli.adapters.driven.rest_watches import V1_CALLS, XSRF, RestWatches
from conflu_c_cli.domain.errors import UnavailableError
from conflu_c_cli.domain.watches import CONTENT, PATHS, SPACE, WatchChange, WatchTarget


class WatchChangeTest(unittest.TestCase):
    def test_a_watch_is_a_post_and_taking_it_off_is_a_delete(self):
        self.assertEqual(WatchChange(CONTENT, "2002", True).method, "POST")
        self.assertEqual(WatchChange(CONTENT, "2002", False).method, "DELETE")

    def test_the_call_is_written_as_the_compatibility_page_writes_it(self):
        self.assertEqual(WatchChange(CONTENT, "2002", True).call, "POST /rest/api/user/watch/content/{contentId}")
        self.assertEqual(WatchChange(CONTENT, "2002", False).call, "DELETE /rest/api/user/watch/content/{contentId}")
        self.assertEqual(WatchChange(SPACE, "ENG", True).call, "POST /rest/api/user/watch/space/{spaceKey}")
        self.assertEqual(WatchChange(SPACE, "ENG", False).call, "DELETE /rest/api/user/watch/space/{spaceKey}")

    def test_every_call_a_change_can_send_has_its_reason_for_v1(self):
        for scope in (CONTENT, SPACE):
            for watch in (True, False):
                with self.subTest(scope=scope, watch=watch):
                    self.assertIn(WatchChange(scope, "x", watch).call, V1_CALLS)
        self.assertEqual(set(PATHS), {CONTENT, SPACE})

    def test_a_change_has_no_place_for_another_person(self):
        """The watch is the one of the token's own account: there is no field, here or below, that could name somebody else."""
        self.assertEqual([field.name for field in dataclasses.fields(WatchChange)], ["scope", "target", "watch"])
        self.assertEqual({field.name for field in dataclasses.fields(WatchTarget)}, {"type", "id", "key", "title", "shown_key"})


class WatchTargetTest(unittest.TestCase):
    def test_content_is_named_by_its_id(self):
        target = WatchTarget("blogpost", "7561")
        self.assertEqual((target.scope, target.name), (CONTENT, "7561"))
        self.assertEqual(target.change(True), WatchChange(CONTENT, "7561", True))
        self.assertEqual(target.change(False), WatchChange(CONTENT, "7561", False))

    def test_a_space_is_named_by_its_key_and_not_by_its_id(self):
        target = WatchTarget(SPACE, "1001", "ENG", "Engineering")
        self.assertEqual((target.scope, target.name), (SPACE, "ENG"))
        self.assertEqual(target.change(True), WatchChange(SPACE, "ENG", True))

    def test_a_personal_space_is_called_by_its_key_though_it_is_printed_as_hidden(self):
        """What is printed (`shown_key`, `title`) is one thing and what the call names (`key`) another: the call needs the real key."""
        target = WatchTarget(SPACE, "1003", "~5b10ac8d82e05b22cc7d4ef5", "[personal space]", "[hidden]")
        self.assertEqual((target.scope, target.name), (SPACE, "~5b10ac8d82e05b22cc7d4ef5"))
        self.assertEqual(target.change(True), WatchChange(SPACE, "~5b10ac8d82e05b22cc7d4ef5", True))

    def test_any_kind_of_content_is_content(self):
        for kind in ("page", "blogpost", "folder", "whiteboard", "database", "embed", "footer-comment", "attachment"):
            with self.subTest(kind=kind):
                self.assertEqual(WatchTarget(kind, "1").scope, CONTENT)


class MappingTest(unittest.TestCase):
    def test_the_status_is_what_the_answer_says_and_nothing_else(self):
        self.assertIs(map_watches.watching_from({"watching": True}), True)
        self.assertIs(map_watches.watching_from({"watching": False}), False)

    def test_an_answer_that_does_not_say_is_none_and_never_false(self):
        for answer in ({}, {"watching": "true"}, {"watching": 1}, {"watching": None}, [], None, "watching", {"status": True}):
            with self.subTest(answer=answer):
                self.assertIsNone(map_watches.watching_from(answer))


class Recorder:
    """What the adapter sends the transport, and the answer it gets: 204, as Confluence says for a watch that was added or taken off."""

    def __init__(self):
        self.requests = []

    def request(self, method, path, **kwargs):
        self.requests.append((method, path, kwargs))
        return HttpResponse(204, {}, b"")


class Probe(RestWatches):
    def __init__(self, answers=()):
        self._transport = Recorder()
        self.answers = list(answers)
        self.calls = []

    def _call(self, method, path, body=None, **kwargs):
        self.calls.append((method, path, body))
        return self.answers.pop(0)

    def _finish(self, response, method, path, expect="object"):
        return None


class AddressTest(unittest.TestCase):
    def test_the_status_is_a_get_of_the_watch_resource_with_nothing_else_in_it(self):
        probe = Probe([{"watching": True}, {"watching": False}])
        self.assertIs(probe.watch_status(CONTENT, "2002"), True)
        self.assertIs(probe.watch_status(SPACE, "ENG"), False)
        self.assertEqual(
            probe.calls,
            [("GET", "/rest/api/user/watch/content/2002", None), ("GET", "/rest/api/user/watch/space/ENG", None)],
        )  # no accountId, no key, no username: the answer is about the owner of the token

    def test_the_write_carries_the_header_the_document_asks_for_and_no_body_and_no_query(self):
        probe = Probe()
        probe.change_watch(WatchChange(CONTENT, "2002", True))
        probe.change_watch(WatchChange(SPACE, "ENG", False))
        self.assertEqual(
            probe._transport.requests,
            [
                ("POST", "/rest/api/user/watch/content/2002", {"headers": XSRF}),
                ("DELETE", "/rest/api/user/watch/space/ENG", {"headers": XSRF}),
            ],
        )
        self.assertEqual(XSRF, {"X-Atlassian-Token": "no-check"})

    def test_what_names_the_resource_is_quoted(self):
        probe = Probe([{"watching": False}])
        probe.watch_status(SPACE, "a/b?x=1#y")
        self.assertEqual(probe.calls[0][1], "/rest/api/user/watch/space/a%2Fb%3Fx%3D1%23y")

    def test_something_that_cannot_be_watched_is_refused_before_anything_is_sent(self):
        probe = Probe()
        for scope in ("label", "user", "", "content/2002/x"):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                probe.watch_status(scope, "x")
            with self.subTest(change=scope), self.assertRaises(ValueError):
                probe.change_watch(WatchChange(scope, "x", True))
        self.assertEqual((probe.calls, probe._transport.requests), ([], []))

    def test_an_answer_that_does_not_say_is_not_taken_for_no(self):
        probe = Probe([{}])
        with self.assertRaises(UnavailableError) as caught:
            probe.watch_status(CONTENT, "2002")
        self.assertIn("did not say whether you watch content 2002", caught.exception.message)


class ReasonsTest(unittest.TestCase):
    def test_the_six_calls_and_why_each_is_v1(self):
        self.assertEqual(
            set(V1_CALLS),
            {
                f"{method} /rest/api/user/watch/{scope}"
                for method in ("GET", "POST", "DELETE")
                for scope in ("content/{contentId}", "space/{spaceKey}")
            },
        )
        for call, reason in V1_CALLS.items():
            with self.subTest(call=call):
                self.assertIn("v2 has no watches", reason)
                self.assertTrue(reason.endswith("."))


if __name__ == "__main__":
    unittest.main()
