"""The rules about tasks that need no Confluence: a task id, a day as epoch milliseconds, a range of due days, what is sent to change a task."""
import dataclasses
import unittest
from datetime import datetime, timezone

from conflu_c_cli.domain.errors import UsageError, ValidationError
from conflu_c_cli.domain.tasks import (
    COMPLETE,
    FIRST_YEAR,
    INCOMPLETE,
    MAX_TASK_ID,
    MAX_TASK_IDS,
    STATUSES,
    Task,
    day_start,
    due_range,
    parse_task_id,
    parse_task_ids,
    status_payload,
)


def epoch_milliseconds(year, month, day):
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp() * 1000)


class TaskIdTest(unittest.TestCase):
    def test_a_task_id_is_a_positive_whole_number_that_is_written_without_leading_zeros(self):
        for text, expected in (("7201", "7201"), (" 7201 ", "7201"), ("1", "1"), ("007", "7"), ("9223372036854775807", "9223372036854775807")):
            with self.subTest(text=text):
                self.assertEqual(parse_task_id(text), expected)

    def test_anything_else_is_invalid_and_the_hint_names_the_list(self):
        for text in (
            "", "   ", "abc", "12 3", "7201\n7202", "-1", "1.5", "7201/../1", "7201?x=1", "9" * 20, "\u0667\u0662\u0660\u0661", "0x1f", "7201;",
            "0", "000", "9223372036854775808", "9" * 19,
        ):
            with self.subTest(text=text), self.assertRaises(ValidationError) as caught:
                parse_task_id(text)
            self.assertIn("conflu tasks", caught.exception.hint)

    def test_the_limit_is_the_largest_id_of_the_api(self):
        self.assertEqual(MAX_TASK_ID, 9223372036854775807)
        self.assertEqual(parse_task_id(str(MAX_TASK_ID)), str(MAX_TASK_ID))
        with self.assertRaises(ValidationError):
            parse_task_id(str(MAX_TASK_ID + 1))

    def test_nothing_is_not_a_task_id(self):
        with self.assertRaises(ValidationError) as caught:
            parse_task_id(None)  # type: ignore[arg-type]
        self.assertIn("<missing>", caught.exception.message)

    def test_what_an_invalid_id_says_back_is_cut(self):
        with self.assertRaises(ValidationError) as caught:
            parse_task_id("x" * 5000)
        self.assertLess(len(caught.exception.message), 100)


class TaskIdsTest(unittest.TestCase):
    def test_the_ids_of_the_option_are_the_ids_of_the_call_in_the_order_they_came_and_each_once(self):
        self.assertEqual(parse_task_ids(["7203", "7201", " 7203 ", "007201", "7202"]), ["7203", "7201", "7202"])

    def test_no_id_is_no_filter(self):
        for values in ([], (), None):
            with self.subTest(values=values):
                self.assertEqual(parse_task_ids(values), [])

    def test_a_text_is_one_id_and_not_a_row_of_characters(self):
        self.assertEqual(parse_task_ids("7201"), ["7201"])
        with self.assertRaises(UsageError):
            parse_task_ids("abc")

    def test_an_id_that_is_none_is_a_usage_error_that_names_the_option_and_the_value(self):
        for text in ("", "  ", "abc", "0", "-5", "1.5", "7201,7202", "7201 7202", "9223372036854775808", "\u0667", "7201\n7202", "../1", "1e3"):
            with self.subTest(text=text), self.assertRaises(UsageError) as caught:
                parse_task_ids(["7201", text])
            self.assertEqual(caught.exception.exit_code, 2)
            self.assertIn("--task needs a task id", caught.exception.message)
            self.assertIn("positive whole number", caught.exception.message)
            self.assertIn("conflu tasks", caught.exception.hint)

    def test_what_a_usage_error_says_back_is_cut(self):
        with self.assertRaises(UsageError) as caught:
            parse_task_ids(["x" * 100_000])
        self.assertLess(len(caught.exception.message), 150)

    def test_the_api_takes_at_most_250_ids_and_the_same_id_again_does_not_count(self):
        every = [str(number) for number in range(1, MAX_TASK_IDS + 1)]
        self.assertEqual(MAX_TASK_IDS, 250)
        self.assertEqual(parse_task_ids(every), every)
        self.assertEqual(parse_task_ids(every + every + ["1"] * 1000), every)
        with self.assertRaises(UsageError) as caught:
            parse_task_ids(every + ["251"])
        self.assertIn("at most 250", caught.exception.message)

    def test_a_hostile_amount_is_refused_without_reading_all_of_it(self):
        with self.assertRaises(UsageError):
            parse_task_ids(str(number) for number in range(1, 10_000_000))  # a generator that would take minutes to read to its end


class DayTest(unittest.TestCase):
    def test_a_day_is_the_start_of_that_day_in_utc_as_milliseconds(self):
        self.assertEqual(day_start("1970-01-01", "--due-after"), 0)
        self.assertEqual(day_start("1970-01-02", "--due-after"), 86_400_000)
        self.assertEqual(day_start("2000-01-01", "--due-after"), 946_684_800_000)  # a day that everybody knows
        self.assertEqual(day_start("2038-01-19", "--due-after"), 2_147_472_000_000)  # the day of the 32 bit limit: no overflow here
        for day in ((2026, 10, 20), (2028, 2, 29), (2026, 12, 31), (9999, 12, 31)):
            with self.subTest(day=day):
                self.assertEqual(day_start("%04d-%02d-%02d" % day, "--due-after"), epoch_milliseconds(*day))

    def test_blanks_around_it_do_not_matter(self):
        self.assertEqual(day_start("  2026-10-20\n", "--due-before"), epoch_milliseconds(2026, 10, 20))

    def test_what_is_no_day_is_a_usage_error_that_names_the_option_and_gives_an_example(self):
        for text in (
            "", "2026-10", "2026-1-5", "26-10-20", "2026/10/20", "2026-10-20T10:00", "2026-10-20 10:00", "2026-13-01", "2026-00-10", "2026-02-30", "2026-04-31",
            "2027-02-29", "2026-10-32", "yesterday", "10/20/2026", "2026-10-20Z", "\u0662\u0660\u0662\u0666-\u0661\u0660-\u0662\u0660", "2026-10-20; DROP", "-2026-10-20",
        ):
            with self.subTest(text=text), self.assertRaises(UsageError) as caught:
                day_start(text, "--due-before")
            self.assertIn("--due-before", caught.exception.message)
            self.assertIn("YYYY-MM-DD", caught.exception.message)
            self.assertIn("2026-10-31", caught.exception.hint)

    def test_a_leap_day_is_a_day_only_in_a_leap_year(self):
        self.assertEqual(day_start("2028-02-29", "--due-after"), epoch_milliseconds(2028, 2, 29))
        self.assertEqual(day_start("2000-02-29", "--due-after"), epoch_milliseconds(2000, 2, 29))
        for text in ("2026-02-29", "1900-02-29"):
            with self.subTest(text=text), self.assertRaises(UsageError):
                day_start(text, "--due-after")

    def test_a_year_before_1970_is_refused_because_it_would_be_negative(self):
        self.assertEqual(FIRST_YEAR, 1970)
        for text in ("1969-12-31", "0001-01-01", "0000-01-01", "1900-06-15"):
            with self.subTest(text=text), self.assertRaises(UsageError) as caught:
                day_start(text, "--due-after")
            self.assertIn("1970", caught.exception.hint)


class DueRangeTest(unittest.TestCase):
    def test_no_day_is_no_limit(self):
        self.assertEqual(due_range(), (None, None))
        self.assertEqual(due_range("", ""), (None, None))

    def test_after_is_the_start_and_before_the_end_and_each_may_stand_alone(self):
        self.assertEqual(due_range(after="2026-10-20"), (epoch_milliseconds(2026, 10, 20), None))
        self.assertEqual(due_range(before="2026-10-31"), (None, epoch_milliseconds(2026, 10, 31)))
        self.assertEqual(due_range("2026-10-20", "2026-10-31"), (epoch_milliseconds(2026, 10, 20), epoch_milliseconds(2026, 10, 31)))

    def test_the_same_day_twice_is_one_instant_and_the_range_holds_the_tasks_due_at_it(self):
        start, end = due_range("2026-10-20", "2026-10-20")
        self.assertEqual(start, end)

    def test_an_after_that_is_later_than_the_before_is_refused_with_both_days(self):
        with self.assertRaises(UsageError) as caught:
            due_range("2026-11-01", "2026-10-01")
        self.assertIn("2026-11-01", caught.exception.message)
        self.assertIn("2026-10-01", caught.exception.message)

    def test_each_day_is_judged_with_its_own_option_name(self):
        with self.assertRaises(UsageError) as after:
            due_range(after="nope")
        self.assertIn("--due-after", after.exception.message)
        with self.assertRaises(UsageError) as before:
            due_range(before="nope")
        self.assertIn("--due-before", before.exception.message)


class StatusPayloadTest(unittest.TestCase):
    def test_the_payload_is_the_status_and_nothing_else(self):
        self.assertEqual(status_payload(COMPLETE), {"status": "complete"})
        self.assertEqual(status_payload(INCOMPLETE), {"status": "incomplete"})
        self.assertEqual(STATUSES, ("incomplete", "complete"))

    def test_a_payload_is_a_new_dict_each_time(self):
        first = status_payload(COMPLETE)
        first["x"] = 1
        self.assertEqual(status_payload(COMPLETE), {"status": "complete"})

    def test_any_other_status_is_refused(self):
        for status in ("", "done", "COMPLETE", "complete ", "open", None):
            with self.subTest(status=status), self.assertRaises(UsageError) as caught:
                status_payload(status)  # type: ignore[arg-type]
            self.assertIn("incomplete", caught.exception.hint)


class TaskTest(unittest.TestCase):
    def test_a_task_has_only_an_id_to_start_with_and_cannot_be_changed(self):
        task = Task("7201")
        self.assertEqual((task.status, task.page_id, task.blogpost_id, task.body, task.created_by, task.assigned_to, task.completed_by), ("", "", "", "", None, None, None))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            task.status = COMPLETE  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
