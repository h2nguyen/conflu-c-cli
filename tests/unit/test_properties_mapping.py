"""What the answers of the REST API v2 for content properties mean: one answer in, a domain object out, and the collection each kind of content has."""
import dataclasses
import unittest

from conflu_c_cli.adapters.driven import rest_properties
from conflu_c_cli.adapters.driven.map_properties import property_from
from conflu_c_cli.domain.properties import ContentProperty

ACCOUNT = "5b10ac8d82e05b22cc7d4ef5"


def answer(**changes):
    data = {
        "id": "7303",
        "key": "team.review",
        "value": {"status": "open", "owners": [ACCOUNT]},
        "version": {"createdAt": "2026-10-10T09:00:00.000Z", "message": "Opened", "number": 3, "minorEdit": False, "authorId": ACCOUNT},
    }
    data.update(changes)
    return data


class PropertyAnswerTest(unittest.TestCase):
    def test_a_property_is_an_id_a_key_a_version_a_value_and_the_time_of_that_version(self):
        item = property_from(answer())
        self.assertEqual(item, ContentProperty("7303", "team.review", 3, {"status": "open", "owners": [ACCOUNT]}, "2026-10-10T09:00:00.000Z"))

    def test_the_author_and_the_message_of_the_version_are_not_carried_on(self):
        names = {field.name for field in dataclasses.fields(property_from(answer()))}
        self.assertEqual(names, {"id", "key", "version", "value", "updated"})
        self.assertNotIn(ACCOUNT, repr(property_from(answer(value=None))))

    def test_a_value_is_any_json_and_stays_as_it_came(self):
        for value in (None, True, False, 0, 1.5, "", "text", [], [1, [2, {"a": None}]], {}, {"a": {"b": [1, 2]}}):
            with self.subTest(value=value):
                self.assertEqual(property_from(answer(value=value)).value, value)

    def test_a_value_that_is_missing_is_nothing(self):
        data = answer()
        del data["value"]
        self.assertIsNone(property_from(data).value)

    def test_what_the_answer_leaves_out_is_empty_and_not_an_error(self):
        item = property_from({"id": "1", "key": "k"})
        self.assertEqual((item.id, item.key, item.version, item.value, item.updated), ("1", "k", 1, None, ""))

    def test_a_version_that_is_no_number_is_the_first(self):
        for number in (None, "3", 3.5, True, [3], {"n": 3}):
            with self.subTest(number=number):
                self.assertEqual(property_from(answer(version={"number": number})).version, 1)
        self.assertEqual(property_from(answer(version="three")).version, 1)
        self.assertEqual(property_from(answer(version=None)).version, 1)

    def test_values_of_the_wrong_type_do_not_break_it(self):
        item = property_from(answer(id=7303, key=None, version={"number": 4, "createdAt": 5}))
        self.assertEqual((item.id, item.key, item.version, item.updated), ("7303", "", 4, "5"))

    def test_an_answer_that_is_no_object_is_a_property_without_an_id(self):
        for data in (None, "x", 3, [], [answer()]):
            with self.subTest(data=data):
                self.assertEqual(property_from(data).id, "")


class CollectionOfKindTest(unittest.TestCase):
    def test_v2_does_it_all_so_no_call_is_v1(self):
        self.assertEqual(rest_properties.V1_CALLS, {})

    def test_a_kind_that_has_no_properties_is_not_turned_into_a_path(self):
        for kind in ("custom", "space", "", "../pages"):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                rest_properties._collection(kind)  # noqa: SLF001

    def test_each_kind_has_its_collection(self):
        self.assertEqual(
            [rest_properties._collection(kind) for kind in ("page", "blogpost", "folder", "whiteboard", "database", "embed", "attachment", "footer-comment", "inline-comment")],
            ["pages", "blogposts", "folders", "whiteboards", "databases", "embeds", "attachments", "comments", "comments"],
        )


if __name__ == "__main__":
    unittest.main()
