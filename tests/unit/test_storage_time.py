"""The storage format parser reads a page in a time that grows with its size, whatever the nesting and the end tags."""
import time
import unittest

from conflu_c_cli.domain.errors import ValidationError
from conflu_c_cli.domain.storage import lossy_constructs, storage_to_markdown, storage_to_text

LIMIT_SECONDS = 3.0  # the work takes a few hundredths of a second; the scan of the stack took minutes for these sizes


def seconds(call, *args) -> float:
    started = time.perf_counter()
    try:
        call(*args)
    except ValidationError:
        pass  # a document that is nested too deeply is refused, which is the right answer; the time is what is measured
    return time.perf_counter() - started


class StorageParserTimeTest(unittest.TestCase):
    def test_end_tags_of_elements_that_are_not_open_cost_nothing(self):
        for shape in ("<div>" * 8000 + "<br></br>" * 8000, "<div>" * 8000 + "</span>" * 20000, "<p>" + "<ri:user></ri:user>" * 20000 + "</p>"):
            with self.subTest(shape=shape[:12]):
                self.assertLess(seconds(storage_to_markdown, shape), LIMIT_SECONDS)
                self.assertLess(seconds(lossy_constructs, shape), LIMIT_SECONDS)
                self.assertLess(seconds(storage_to_text, shape), LIMIT_SECONDS)

    def test_the_tree_is_what_it_was(self):
        self.assertEqual(storage_to_markdown("<p>one <strong>two</strong> three</p><ul><li>a</li><li>b</li></ul>").text, "one **two** three\n\n- a\n- b")
        self.assertEqual(storage_to_text("<div><p>a</p><span>b</span></div></span></p>x"), storage_to_text("<div><p>a</p><span>b</span></div>x"))
        self.assertEqual(storage_to_text("<p>a<b>bold</i>still bold</b>c</p>"), "abold" + "still boldc")


if __name__ == "__main__":
    unittest.main()
