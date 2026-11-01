"""What the core mapper reads of an answer, and what it makes of an answer that lacks what it reads (`adapters/driven/confluence_mapper.py`)."""
import unittest

from conflu_c_cli.adapters.driven import confluence_mapper as mapper


class LabelsCutTest(unittest.TestCase):
    """The documents limit what an `include-labels` adds to 50 results, and say that `labels.meta.hasMore` tells whether there are more."""

    def test_an_answer_that_says_there_are_more_labels_is_cut(self):
        self.assertTrue(mapper.labels_cut({"id": "1", "labels": {"results": [], "meta": {"hasMore": True, "cursor": "50"}}}))

    def test_an_answer_that_says_there_are_no_more_or_says_nothing_is_not(self):
        for data in (
            {"labels": {"results": [], "meta": {"hasMore": False}}},
            {"labels": {"results": []}},
            {"labels": {"results": [], "meta": {"hasMore": None}}},
            {"labels": {"results": [], "meta": {"hasMore": "true"}}},  # only the boolean that the document describes counts
            {"labels": None},
            {"labels": []},
            {},
            None,
            "text",
        ):
            with self.subTest(data=data):
                self.assertFalse(mapper.labels_cut(data))

    def test_the_page_keeps_the_labels_that_the_answer_holds(self):
        page = mapper.page_from({"id": "1", "labels": {"results": [{"id": "9", "name": "a", "prefix": "global"}, {"id": "10", "name": "b"}], "meta": {"hasMore": True}}})
        self.assertEqual([(label.name, label.prefix) for label in page.labels], [("a", "global"), ("b", "global")])


class SearchLabelsTest(unittest.TestCase):
    """The v1 document says `Content.metadata.labels` is a LabelArray (`{results: [...]}`) or a plain array of labels: a hit keeps the labels of both."""

    def labels_of(self, labels):
        return mapper.search_hit_from({"content": {"id": "1", "type": "page", "metadata": {"labels": labels}}}).labels

    def test_a_label_array_and_a_plain_array_give_the_same_labels(self):
        entries = [{"id": "9", "name": "Draft", "prefix": "global"}, {"id": "10", "name": "plan"}, {"id": "11", "name": "DRAFT"}]
        self.assertEqual(self.labels_of({"results": entries, "size": 3}), ("draft", "plan"))
        self.assertEqual(self.labels_of(entries), ("draft", "plan"))

    def test_an_answer_without_labels_gives_none(self):
        for labels in ({}, {"results": []}, {"results": None}, [], None, "text", [None, "x", {"name": ""}]):
            with self.subTest(labels=labels):
                self.assertEqual(self.labels_of(labels), ())
        self.assertEqual(mapper.search_hit_from({"content": {"id": "1"}}).labels, ())


if __name__ == "__main__":
    unittest.main()
