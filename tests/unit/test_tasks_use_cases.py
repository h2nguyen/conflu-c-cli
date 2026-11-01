"""The use cases around the tasks that are written into pages, against the fake Confluence: list with every filter, show one, complete and reopen one."""
import dataclasses
import unittest
from unittest import mock

from conflu_c_cli.application.tasks import UNREADABLE, present
from conflu_c_cli.domain.errors import NotFoundError, UnavailableError, UsageError, ValidationError
from conflu_c_cli.domain.model import User
from conflu_c_cli.domain.tasks import Task
from tests.support.fakes import ACCOUNT, BASE, FakeGateway, RecordingDiagnostics, build_app, default_settings
from tests.support.fakes_tasks import BLOG_POST, SAM


def fresh(**settings):
    gateway = FakeGateway()
    diagnostics = RecordingDiagnostics()
    app = build_app(gateway=gateway, settings=default_settings(**settings), diagnostics=diagnostics)
    return app, gateway, diagnostics


def ids(result):
    return [view.task.id for view in result.tasks]


def listed(gateway):
    """The arguments of the last call of `list_tasks`, by name."""
    names = ("status", "task_ids", "space_ids", "page_ids", "blogpost_ids", "assigned_to", "created_by", "due_from", "due_to", "limit", "cursor")
    return dict(zip(names, gateway.called("list_tasks")[-1][1:]))


class ListTasksTest(unittest.TestCase):
    def test_the_whole_site_comes_a_piece_at_a_time_with_the_cursor_of_the_next_piece(self):
        app, gateway, _ = fresh()
        first = app.tasks.list_tasks.execute()
        self.assertEqual((ids(first), first.next_cursor, first.truncated, first.space), (["7201", "7202"], "2", False, None))
        self.assertEqual(
            listed(gateway),
            dict(status="", task_ids=(), space_ids=(), page_ids=(), blogpost_ids=(), assigned_to=(), created_by=(), due_from=None, due_to=None, limit=25, cursor=""),
        )
        second = app.tasks.list_tasks.execute(cursor=first.next_cursor)
        self.assertEqual((ids(second), second.next_cursor), (["7203", "7204"], "4"))
        self.assertEqual(ids(app.tasks.list_tasks.execute(cursor="4")), ["7205", "7206"])
        self.assertEqual(app.tasks.list_tasks.execute(cursor="4").next_cursor, "")

    def test_all_of_them_is_read_in_big_pieces_until_the_end(self):
        app, gateway, _ = fresh()
        result = app.tasks.list_tasks.execute(fetch_everything=True, limit=1)
        self.assertEqual((ids(result), result.next_cursor, result.truncated), (["7201", "7202", "7203", "7204", "7205", "7206"], "", False))
        self.assertEqual({call[-2] for call in gateway.called("list_tasks")}, {100})  # the size of a piece for all of it, whatever --limit says

    def test_the_text_of_a_task_is_plain_text_without_the_people_in_it(self):
        app, _, _ = fresh()
        by_id = {view.task.id: view for view in app.tasks.list_tasks.execute(fetch_everything=True).tasks}
        self.assertEqual(by_id["7201"].text, "Check the numbers with @user")  # a mention
        self.assertEqual(by_id["7204"].text, "Mail [email] about the plan")  # an address
        self.assertEqual(by_id["7202"].text, "Publish the release notes")
        for view in by_id.values():
            self.assertEqual(view.task.body, "")  # the storage format is not carried on

    def test_nobody_is_named_unless_the_people_are_asked_for(self):
        app, gateway, _ = fresh()
        result = app.tasks.list_tasks.execute(fetch_everything=True)
        self.assertFalse(result.users_shown)
        for view in result.tasks:
            self.assertEqual((view.task.created_by, view.task.assigned_to, view.task.completed_by), (None, None, None))
        self.assertEqual(gateway.called("lookup_users"), [])
        self.assertNotIn(ACCOUNT, repr(result))

    def test_a_status_keeps_the_tasks_in_that_state(self):
        app, gateway, _ = fresh()
        self.assertEqual(ids(app.tasks.list_tasks.execute(status="complete", fetch_everything=True)), ["7202"])
        self.assertEqual(listed(gateway)["status"], "complete")
        self.assertEqual(ids(app.tasks.list_tasks.execute(status="incomplete", fetch_everything=True)), ["7201", "7203", "7204", "7205", "7206"])

    def test_an_unknown_status_is_a_usage_error_and_nothing_is_asked(self):
        app, gateway, _ = fresh()
        for status in ("done", "COMPLETE", "open"):
            with self.subTest(status=status), self.assertRaises(UsageError) as caught:
                app.tasks.list_tasks.execute(status=status)
            self.assertIn("incomplete", caught.exception.hint)
        self.assertEqual(gateway.calls, [])

    def test_a_space_is_found_by_its_key_and_its_id_is_the_filter(self):
        app, gateway, _ = fresh()
        result = app.tasks.list_tasks.execute(space="eng", fetch_everything=True)
        self.assertEqual((result.space.key, result.space.id), ("ENG", "1001"))
        self.assertEqual(ids(result), ["7201", "7202", "7203", "7204", "7205"])
        self.assertEqual(listed(gateway)["space_ids"], ("1001",))
        self.assertEqual(ids(app.tasks.list_tasks.execute(space="DOCS")), ["7206"])

    def test_a_space_that_is_not_there_is_not_found_and_no_task_is_asked_for(self):
        app, gateway, _ = fresh()
        with self.assertRaises(NotFoundError):
            app.tasks.list_tasks.execute(space="NOPE")
        self.assertEqual(gateway.called("list_tasks"), [])
        for key in ("E N G", "ENG/../x", "a" * 300):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                app.tasks.list_tasks.execute(space=key)

    def test_a_page_is_asked_what_it_is_once_and_a_blog_post_goes_into_the_other_filter(self):
        app, gateway, _ = fresh()
        self.assertEqual(ids(app.tasks.list_tasks.execute(page="2002", fetch_everything=True)), ["7201", "7202"])
        self.assertEqual((listed(gateway)["page_ids"], listed(gateway)["blogpost_ids"]), (("2002",), ()))
        self.assertEqual(gateway.called("content_types"), [("content_types", ("2002",))])
        self.assertEqual(ids(app.tasks.list_tasks.execute(page=BLOG_POST)), ["7205"])
        self.assertEqual((listed(gateway)["page_ids"], listed(gateway)["blogpost_ids"]), ((), (BLOG_POST,)))

    def test_the_address_of_a_page_is_a_page(self):
        app, gateway, _ = fresh()
        app.tasks.list_tasks.execute(page=f"{BASE}/spaces/ENG/pages/2003/Architecture")
        self.assertEqual(listed(gateway)["page_ids"], ("2003",))

    def test_content_that_cannot_hold_tasks_is_refused_and_says_what_it_is(self):
        app, gateway, _ = fresh()
        with self.assertRaises(ValidationError) as caught:
            app.tasks.list_tasks.execute(page="7001")
        self.assertIn("a folder", caught.exception.message)
        self.assertEqual(caught.exception.details, {"id": "7001", "type": "folder"})
        with self.assertRaises(NotFoundError) as missing:
            app.tasks.list_tasks.execute(page="99999")
        self.assertEqual(missing.exception.details, {"id": "99999"})
        with self.assertRaises(ValidationError):
            app.tasks.list_tasks.execute(page="not an id")
        self.assertEqual(gateway.called("list_tasks"), [])

    def test_mine_asks_who_the_token_belongs_to_and_filters_on_it_without_showing_it(self):
        app, gateway, _ = fresh()
        result = app.tasks.list_tasks.execute(mine=True, fetch_everything=True)
        self.assertEqual(ids(result), ["7201", "7203", "7205"])
        self.assertEqual(gateway.called("current_user"), [("current_user",)])
        self.assertEqual((listed(gateway)["assigned_to"], listed(gateway)["created_by"]), ((ACCOUNT,), ()))
        self.assertNotIn(ACCOUNT, repr(result))

    def test_created_by_me_filters_on_the_creator(self):
        app, gateway, _ = fresh()
        result = app.tasks.list_tasks.execute(created_by_me=True, fetch_everything=True)
        self.assertEqual(ids(result), ["7201", "7202", "7204", "7205"])
        self.assertEqual((listed(gateway)["assigned_to"], listed(gateway)["created_by"]), ((), (ACCOUNT,)))

    def test_both_together_need_one_question_and_every_filter_has_to_hold(self):
        app, gateway, _ = fresh()
        result = app.tasks.list_tasks.execute(mine=True, created_by_me=True, status="incomplete", fetch_everything=True)
        self.assertEqual(ids(result), ["7201", "7205"])
        self.assertEqual(len(gateway.called("current_user")), 1)

    def test_a_token_that_names_nobody_cannot_be_used_for_mine(self):
        app, gateway, _ = fresh()
        gateway.user = User("")
        with self.assertRaises(ValidationError) as caught:
            app.tasks.list_tasks.execute(mine=True)
        self.assertIn("conflu ping", caught.exception.hint)
        self.assertEqual(gateway.called("list_tasks"), [])

    def test_a_range_of_due_days_is_in_milliseconds_and_includes_both_ends(self):
        app, gateway, _ = fresh()
        result = app.tasks.list_tasks.execute(due_after="2026-10-20", due_before="2026-10-25", fetch_everything=True)
        self.assertEqual(ids(result), ["7201", "7205"])  # due exactly at the start of the first and of the last day
        self.assertEqual((listed(gateway)["due_from"], listed(gateway)["due_to"]), (1_792_454_400_000, 1_792_886_400_000))
        self.assertEqual(ids(app.tasks.list_tasks.execute(due_before="2026-10-10", fetch_everything=True)), ["7202"])
        self.assertEqual(ids(app.tasks.list_tasks.execute(due_after="2026-12-01", fetch_everything=True)), ["7206"])

    def test_a_task_without_a_due_date_is_in_no_range(self):
        app, _, _ = fresh()
        self.assertIn("7204", ids(app.tasks.list_tasks.execute(fetch_everything=True)))
        self.assertNotIn("7204", ids(app.tasks.list_tasks.execute(due_after="1970-01-01", fetch_everything=True)))
        self.assertNotIn("7204", ids(app.tasks.list_tasks.execute(due_before="9999-12-31", fetch_everything=True)))

    def test_a_date_that_is_no_day_is_refused_before_anything_is_asked(self):
        app, gateway, _ = fresh()
        for arguments in ({"due_before": "2026-02-30"}, {"due_after": "next week"}, {"due_after": "2026-11-01", "due_before": "2026-10-01"}, {"due_after": "1969-12-31"}):
            with self.subTest(arguments=arguments), self.assertRaises(UsageError):
                app.tasks.list_tasks.execute(mine=True, space="ENG", **arguments)
        self.assertEqual(gateway.calls, [])

    def test_with_users_looks_the_people_up_once_and_names_those_that_are_known(self):
        app, gateway, _ = fresh()
        gateway.users[SAM.account_id] = SAM
        result = app.tasks.list_tasks.execute(fetch_everything=True, with_users=True)
        self.assertTrue(result.users_shown)
        self.assertEqual(gateway.called("lookup_users"), [("lookup_users", tuple(sorted([ACCOUNT, SAM.account_id])))])
        by_id = {view.task.id: view.task for view in result.tasks}
        self.assertEqual((by_id["7201"].assigned_to, by_id["7201"].created_by, by_id["7201"].completed_by), (gateway.users[ACCOUNT], gateway.users[ACCOUNT], None))
        self.assertEqual((by_id["7202"].assigned_to.display_name, by_id["7202"].completed_by.display_name), ("Sam Example", "Sam Example"))
        self.assertEqual(by_id["7201"].assigned_to.email, "alex@example.com")

    def test_a_person_that_is_not_described_stays_an_id(self):
        app, _, _ = fresh()
        result = app.tasks.list_tasks.execute(page="2002", with_users=True, fetch_everything=True)
        sam = next(view.task.assigned_to for view in result.tasks if view.task.id == "7202")
        self.assertEqual(sam, User(SAM.account_id))

    def test_a_failed_lookup_leaves_the_ids_and_says_so(self):
        app, gateway, diagnostics = fresh()
        gateway.errors["lookup_users"] = UnavailableError("The lookup failed.")
        result = app.tasks.list_tasks.execute(page="2002", with_users=True, fetch_everything=True)
        self.assertEqual(result.tasks[0].task.assigned_to, User(ACCOUNT))
        self.assertEqual(len(diagnostics.warnings), 1)
        self.assertIn("Could not look up", diagnostics.warnings[0])

    def test_the_people_are_not_available_under_the_policy_that_hides_them(self):
        app, gateway, _ = fresh(hide_users=True)
        with self.assertRaises(ValidationError) as caught:
            app.tasks.list_tasks.execute(with_users=True)
        self.assertIn("CONFLUENCE_HIDE_USERS", caught.exception.message)
        self.assertEqual(gateway.calls, [])
        self.assertEqual(ids(app.tasks.list_tasks.execute(fetch_everything=True)), ["7201", "7202", "7203", "7204", "7205", "7206"])  # the rest still works

    def test_a_limit_is_handed_on(self):
        app, gateway, _ = fresh()
        app.tasks.list_tasks.execute(limit=7)
        self.assertEqual(listed(gateway)["limit"], 7)

    def test_the_ids_that_are_asked_for_are_the_filter_and_nothing_else_is_asked_for(self):
        app, gateway, _ = fresh()
        result = app.tasks.list_tasks.execute(task_ids=["7203", "7201"])
        self.assertEqual(ids(result), ["7201", "7203"])  # by id, as every list is
        self.assertEqual(listed(gateway)["task_ids"], ("7203", "7201"))
        self.assertEqual((result.next_cursor, result.truncated, result.space), ("", False, None))
        self.assertEqual(sorted({call[0] for call in gateway.calls}), ["list_tasks"])  # no space, no page, no user: one request

    def test_one_task_is_read_by_its_id_in_one_request_with_its_text_and_nobody_named(self):
        app, gateway, _ = fresh()
        result = app.tasks.list_tasks.execute(task_ids=["7204"])
        view = result.tasks[0]
        self.assertEqual((ids(result), view.text), (["7204"], "Mail [email] about the plan"))
        self.assertEqual((view.task.created_by, view.task.assigned_to, view.task.body), (None, None, ""))
        self.assertNotIn(ACCOUNT, repr(result))
        self.assertEqual(len(gateway.calls), 1)

    def test_an_id_given_twice_or_with_zeros_is_sent_once_as_a_plain_number(self):
        app, gateway, _ = fresh()
        app.tasks.list_tasks.execute(task_ids=["7201", " 7201 ", "07201", "7202"])
        self.assertEqual(listed(gateway)["task_ids"], ("7201", "7202"))

    def test_an_id_that_no_task_has_is_not_in_the_list_and_is_no_error(self):
        app, gateway, _ = fresh()
        result = app.tasks.list_tasks.execute(task_ids=["7201", "99999"])
        self.assertEqual(ids(result), ["7201"])
        self.assertEqual(ids(app.tasks.list_tasks.execute(task_ids=["99999"])), [])

    def test_every_filter_that_is_given_has_to_hold_with_the_ids_too(self):
        app, gateway, _ = fresh()
        self.assertEqual(ids(app.tasks.list_tasks.execute(task_ids=["7201", "7202", "7203"], status="complete")), ["7202"])
        self.assertEqual(ids(app.tasks.list_tasks.execute(task_ids=["7201", "7205"], page="2002")), ["7201"])
        self.assertEqual(ids(app.tasks.list_tasks.execute(task_ids=["7201", "7203", "7206"], space="DOCS")), ["7206"])
        self.assertEqual(ids(app.tasks.list_tasks.execute(task_ids=["7201", "7203"], mine=True, due_before="2026-10-31")), ["7201"])
        last = listed(gateway)
        self.assertEqual((last["task_ids"], last["assigned_to"], last["due_to"] is not None), (("7201", "7203"), (ACCOUNT,), True))

    def test_the_ids_come_in_pieces_like_every_list_and_all_of_them_in_big_pieces(self):
        app, gateway, _ = fresh()
        every = ["7201", "7202", "7203", "7204", "7205", "7206"]
        first = app.tasks.list_tasks.execute(task_ids=every)
        self.assertEqual((ids(first), first.next_cursor), (["7201", "7202"], "2"))  # the fake gives two at most in a piece
        self.assertEqual(ids(app.tasks.list_tasks.execute(task_ids=every, cursor=first.next_cursor)), ["7203", "7204"])
        self.assertEqual(ids(app.tasks.list_tasks.execute(task_ids=every, fetch_everything=True, limit=1)), every)
        self.assertEqual(listed(gateway)["limit"], 100)

    def test_the_people_of_the_tasks_that_were_asked_for_are_shown_only_when_asked(self):
        app, gateway, _ = fresh()
        gateway.users[SAM.account_id] = SAM
        plain = app.tasks.list_tasks.execute(task_ids=["7202"])
        self.assertEqual((plain.tasks[0].task.assigned_to, plain.users_shown), (None, False))
        shown = app.tasks.list_tasks.execute(task_ids=["7202"], with_users=True)
        self.assertEqual((shown.tasks[0].task.assigned_to.display_name, shown.users_shown), ("Sam Example", True))

    def test_an_id_that_is_no_task_id_is_a_usage_error_and_nothing_is_asked(self):
        app, gateway, _ = fresh()
        for text in ("abc", "0", "-1", "7201,7202", "1.5", "9223372036854775808", ""):
            with self.subTest(text=text), self.assertRaises(UsageError) as caught:
                app.tasks.list_tasks.execute(task_ids=["7201", text], mine=True, space="ENG", page="2002")
            self.assertIn("--task", caught.exception.message)
        self.assertEqual(gateway.calls, [])

    def test_more_than_250_ids_are_refused_before_anything_is_asked_and_exactly_250_go_through(self):
        app, gateway, _ = fresh()
        every = [str(number) for number in range(8000, 8250)]
        self.assertEqual(ids(app.tasks.list_tasks.execute(task_ids=every)), [])
        self.assertEqual(len(listed(gateway)["task_ids"]), 250)
        gateway.calls.clear()
        with self.assertRaises(UsageError) as caught:
            app.tasks.list_tasks.execute(task_ids=every + ["8250"], mine=True)
        self.assertIn("at most 250", caught.exception.message)
        self.assertEqual(gateway.calls, [])

    def test_the_policy_that_hides_people_does_not_stand_in_the_way_of_the_ids(self):
        app, gateway, _ = fresh(hide_users=True)
        self.assertEqual(ids(app.tasks.list_tasks.execute(task_ids=["7201"])), ["7201"])
        with self.assertRaises(ValidationError):
            app.tasks.list_tasks.execute(task_ids=["7201"], with_users=True)


class PresentTest(unittest.TestCase):
    def test_the_text_is_one_line_of_plain_text(self):
        task = Task("1", body="<p>One</p><p>Two <strong>words</strong></p><ul><li>x</li></ul>")
        self.assertEqual(present(task).text, "One Two words - x")

    def test_without_the_people_asked_for_nobody_is_in_the_view_even_when_the_task_names_them(self):
        task = Task("1", created_by=User(ACCOUNT), assigned_to=User(ACCOUNT, "Alex Example", "alex@example.com"), completed_by=User(ACCOUNT))
        shown = present(task).task
        self.assertEqual((shown.created_by, shown.assigned_to, shown.completed_by), (None, None, None))

    def test_with_the_people_asked_for_the_names_that_are_known_are_put_in(self):
        task = Task("1", created_by=User(ACCOUNT), assigned_to=User("somebody"))
        shown = present(task, with_users=True, known={ACCOUNT: User(ACCOUNT, "Alex Example", "alex@example.com")}).task
        self.assertEqual((shown.created_by.display_name, shown.assigned_to), ("Alex Example", User("somebody")))

    def test_a_mention_shows_its_account_id_only_when_the_people_are_shown(self):
        task = Task("1", body=f'<span>Ask <ac:link><ri:user ri:account-id="{ACCOUNT}" /></ac:link></span>')
        self.assertNotIn(ACCOUNT, present(task).text)
        self.assertIn(ACCOUNT, present(task, with_users=True).text)

    def test_a_text_that_nests_too_deeply_to_convert_is_said_so_and_does_not_stop_the_other_tasks(self):
        hostile = Task("7299", "incomplete", "1001", "2002", body="<div>" * 200 + "x" + "</div>" * 200)
        self.assertEqual(present(hostile).text, UNREADABLE)
        app, gateway, _ = fresh()
        gateway.tasks["7299"] = hostile
        texts = {view.task.id: view.text for view in app.tasks.list_tasks.execute(fetch_everything=True).tasks}
        self.assertEqual((texts["7299"], texts["7201"], texts["7206"]), (UNREADABLE, "Check the numbers with @user", "Update the docs home"))

    def test_whatever_the_converter_does_to_a_text_it_is_a_text_that_cannot_be_shown(self):
        task = Task("1", "incomplete", "1001", "2002", body="<p>x</p>")
        for failure in (ValidationError("cannot read this body"), AssertionError("unknown status keyword 'foo' in marked section"), ValueError("invalid literal"), RuntimeError("any"), MemoryError()):
            with self.subTest(failure=type(failure).__name__), mock.patch("conflu_c_cli.application.tasks.render_body", side_effect=failure):
                view = present(task)
                self.assertEqual((view.text, view.task.id), (UNREADABLE, "1"))
        self.assertIn("nests too deeply", UNREADABLE)  # the words that the first of the two reasons has had since the first version
        self.assertIn("cannot be read", UNREADABLE)


class ShowTaskTest(unittest.TestCase):
    def test_a_task_is_shown_with_its_text_and_nobody_named(self):
        app, gateway, _ = fresh()
        view = app.tasks.show_task.execute("7201")
        self.assertEqual((view.task.id, view.task.status, view.task.page_id, view.task.due, view.text), ("7201", "incomplete", "2002", "2026-10-20T00:00:00.000Z", "Check the numbers with @user"))
        self.assertEqual((view.task.created_by, view.task.assigned_to), (None, None))
        self.assertEqual(gateway.called("get_task"), [("get_task", "7201")])

    def test_a_task_that_is_not_there_is_not_found_and_a_bad_id_asks_nothing(self):
        app, gateway, _ = fresh()
        with self.assertRaises(NotFoundError):
            app.tasks.show_task.execute("99999")
        gateway.calls.clear()
        for text in ("", "abc", "7201/../x", "-1"):
            with self.subTest(text=text), self.assertRaises(ValidationError):
                app.tasks.show_task.execute(text)
        self.assertEqual(gateway.calls, [])


class ChangeTaskTest(unittest.TestCase):
    def steps(self, gateway):
        return [call for call in gateway.calls if call[0] in ("get_task", "update_task")]

    def test_a_task_is_read_then_changed_with_the_status_alone_and_read_again(self):
        app, gateway, _ = fresh()
        result = app.tasks.change_task.execute("7201", "complete")
        self.assertEqual(self.steps(gateway), [("get_task", "7201"), ("update_task", "7201", {"status": "complete"}), ("get_task", "7201")])
        self.assertEqual((result.action, result.status_from, result.status_to, result.dry_run, result.read_back, result.notes), ("completed", "incomplete", "complete", False, True, []))
        self.assertEqual(result.payload, {"status": "complete"})
        self.assertEqual(result.task.task.status, "complete")  # as Confluence holds it now
        self.assertEqual(gateway.tasks["7201"].status, "complete")
        self.assertEqual(result.task.task.assigned_to, None)  # nobody is named in the view of the change either

    def test_it_can_be_reopened(self):
        app, gateway, _ = fresh()
        result = app.tasks.change_task.execute("7202", "incomplete")
        self.assertEqual((result.action, result.status_from, result.status_to, result.read_back), ("reopened", "complete", "incomplete", True))
        self.assertEqual((gateway.tasks["7202"].status, gateway.tasks["7202"].completed), ("incomplete", ""))

    def test_a_task_that_is_in_the_state_asked_for_is_left_alone(self):
        app, gateway, _ = fresh()
        for task_id, status in (("7201", "incomplete"), ("7202", "complete")):
            with self.subTest(task=task_id):
                result = app.tasks.change_task.execute(task_id, status)
                self.assertEqual((result.action, result.payload, result.dry_run, result.read_back, result.status_from, result.status_to), ("unchanged", None, False, False, status, status))
        self.assertEqual(gateway.called("update_task"), [])
        self.assertEqual(len(gateway.called("get_task")), 2)  # read, and nothing else

    def test_a_dry_run_reads_the_task_and_sends_nothing_and_shows_what_would_be_sent(self):
        app, gateway, _ = fresh()
        before = gateway.tasks["7201"]
        result = app.tasks.change_task.execute("7201", "complete", dry_run=True)
        self.assertEqual(self.steps(gateway), [("get_task", "7201")])
        self.assertEqual((result.action, result.dry_run, result.payload, result.read_back, result.status_from, result.status_to), ("completed", True, {"status": "complete"}, False, "incomplete", "complete"))
        self.assertEqual(result.task.task.status, "incomplete")  # the task as it is
        self.assertEqual(gateway.tasks["7201"], before)

    def test_a_dry_run_of_what_is_so_already_says_so(self):
        app, gateway, _ = fresh()
        result = app.tasks.change_task.execute("7202", "complete", dry_run=True)
        self.assertEqual((result.action, result.dry_run, result.payload), ("unchanged", True, None))
        self.assertEqual(gateway.called("update_task"), [])

    def test_what_is_sent_is_what_the_dry_run_showed(self):
        app, gateway, _ = fresh()
        preview = app.tasks.change_task.execute("7203", "complete", dry_run=True).payload
        app.tasks.change_task.execute("7203", "complete")
        self.assertEqual(gateway.called("update_task"), [("update_task", "7203", preview)])

    def test_a_task_that_is_not_there_is_not_found_and_nothing_is_sent(self):
        app, gateway, _ = fresh()
        with self.assertRaises(NotFoundError):
            app.tasks.change_task.execute("99999", "complete")
        self.assertEqual(gateway.called("update_task"), [])

    def test_a_bad_id_or_a_bad_status_asks_nothing(self):
        app, gateway, _ = fresh()
        with self.assertRaises(ValidationError):
            app.tasks.change_task.execute("7201/x", "complete")
        with self.assertRaises(UsageError):
            app.tasks.change_task.execute("7201", "done")
        self.assertEqual(gateway.calls, [])

    def test_a_change_that_cannot_be_read_back_is_still_a_change_and_says_so(self):
        app, gateway, _ = fresh()
        original = gateway.get_task
        reads = []

        def second_read_fails(task_id):
            reads.append(task_id)
            if len(reads) > 1:
                raise UnavailableError("Confluence answered with a server error (HTTP 500).")
            return original(task_id)

        gateway.get_task = second_read_fails
        result = app.tasks.change_task.execute("7201", "complete")
        self.assertEqual((result.action, result.read_back, gateway.tasks["7201"].status), ("completed", False, "complete"))
        self.assertEqual(len(result.notes), 1)
        self.assertIn("could not be read back", result.notes[0])
        self.assertEqual(result.task.task.status, "complete")  # what Confluence answered to the change

    def test_a_task_that_somebody_changed_again_is_reported_as_it_is_now(self):
        app, gateway, _ = fresh()
        original = gateway.get_task

        def reopened_meanwhile(task_id):
            task = original(task_id)
            return dataclasses.replace(task, status="incomplete") if gateway.called("update_task") else task

        gateway.get_task = reopened_meanwhile
        result = app.tasks.change_task.execute("7201", "complete")
        self.assertEqual((result.action, result.read_back, result.task.task.status), ("completed", True, "incomplete"))
        self.assertIn("incomplete", result.notes[0])
        self.assertIn("changed it again", result.notes[0])

    def test_what_the_read_after_the_change_shows_decides_whether_it_is_confirmed(self):
        app, gateway, _ = fresh()
        done = app.tasks.change_task.execute("7201", "complete")
        self.assertEqual((done.confirmed, done.message, done.notes), (True, "", []))
        undone = app.tasks.change_task.execute("7202", "incomplete")
        self.assertEqual((undone.confirmed, undone.message, undone.notes), (True, "", []))

    def test_a_change_that_was_accepted_and_not_made_is_not_confirmed_and_says_how_to_look(self):
        app, gateway, _ = fresh()
        gateway.update_task = lambda task_id, payload: gateway.tasks[task_id]  # a server that says yes and does nothing
        result = app.tasks.change_task.execute("7203", "complete")
        self.assertEqual((result.action, result.read_back, result.confirmed, result.task.task.status), ("completed", True, False, "incomplete"))
        self.assertEqual(
            result.message,
            "Confluence accepted the change, but it holds task 7203 as incomplete, not as complete. Somebody may have changed it again; check it with `conflu task 7203 --json` (status).",
        )
        self.assertEqual(result.notes, [result.message])

    def test_a_change_that_could_not_be_read_back_is_neither_confirmed_nor_denied(self):
        app, gateway, _ = fresh()
        original = gateway.get_task
        reads = []

        def second_read_fails(task_id):
            reads.append(task_id)
            if len(reads) > 1:
                raise UnavailableError("Confluence answered with a server error (HTTP 500).")
            return original(task_id)

        gateway.get_task = second_read_fails
        result = app.tasks.change_task.execute("7201", "complete")
        self.assertEqual((result.read_back, result.confirmed), (False, None))
        self.assertEqual(result.notes, [result.message])
        self.assertIn("could not be read back", result.message)

    def test_a_dry_run_and_a_task_that_is_in_the_state_already_have_nothing_to_confirm(self):
        app, gateway, _ = fresh()
        for task_id, status, dry_run in (("7201", "complete", True), ("7202", "complete", False), ("7202", "complete", True)):
            result = app.tasks.change_task.execute(task_id, status, dry_run=dry_run)
            with self.subTest(task=task_id, dry_run=dry_run):
                self.assertEqual((result.confirmed, result.message, result.notes), (None, "", []))


if __name__ == "__main__":
    unittest.main()
