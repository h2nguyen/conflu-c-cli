"""The parts of a Markdown page: outline, one section, and a cut that does not split a paragraph or a code block."""
import unittest

from conflu_c_cli.domain.errors import ValidationError
from conflu_c_cli.domain.sections import extract_section, outline, plain_title, truncate

PAGE = (
    "# Background\n\nQA derives roles from groups.\n\n"
    "## Prerequisites\n\n- A user with several groups gets the highest role.\n\n```bash\n# not a heading\nconfig set X\n```\n\n"
    "## Steps\n\n1. Open the portal.\n2. Choose the service.\n\n### Texts to copy\n\nSome text.\n\n"
    "## Recommended members\n\nThe product owner.\n"
)


class OutlineTest(unittest.TestCase):
    def test_headings_levels_and_the_size_of_each_section(self):
        found = outline(PAGE)
        self.assertEqual([(h.index, h.level, h.title) for h in found], [(1, 1, "Background"), (2, 2, "Prerequisites"), (3, 2, "Steps"), (4, 3, "Texts to copy"), (5, 2, "Recommended members")])
        by_title = {h.title: h for h in found}
        self.assertEqual(by_title["Background"].chars, len(PAGE.rstrip()))  # the first heading holds the whole page
        self.assertGreater(by_title["Steps"].chars, by_title["Texts to copy"].chars)  # a section holds its sub-sections
        self.assertEqual(by_title["Recommended members"].chars, len("## Recommended members\n\nThe product owner."))

    def test_a_hash_in_a_code_block_is_not_a_heading_whatever_the_fence(self):
        for fence in ("```", "````", "~~~"):
            with self.subTest(fence=fence):
                text = f"# One\n\n{fence}\n# not\n## nor this\n{fence}\n\n## Two\n"
                self.assertEqual([h.title for h in outline(text)], ["One", "Two"])

    def test_a_longer_fence_is_not_closed_by_a_shorter_one(self):
        text = "# One\n\n````\n```\n# inside\n```\n````\n\n## Two\n"
        self.assertEqual([h.title for h in outline(text)], ["One", "Two"])

    def test_only_a_fence_of_up_to_three_spaces_closes_a_block(self):
        fence = "`" * 3
        text = f"# One\n\n{fence}\n    {fence}\n# inside\n{fence}\n\n## Two\n"  # four spaces: still code, as in CommonMark
        self.assertEqual([h.title for h in outline(text)], ["One", "Two"])
        for closing in (f"   {fence}", f"{fence}  ", fence + "`"):
            with self.subTest(closing=closing):
                self.assertEqual([h.title for h in outline(f"{fence}\ncode\n{closing}\n# After\n")], ["After"])
        self.assertEqual([h.title for h in outline(f"{fence}\ncode\n{fence} text\n# Still code\n")], [])  # a fence with text after it does not close
        self.assertEqual([h.title for h in outline("~~~\ncode\n```\n# Still code\n~~~\n# After\n")], ["After"])  # another character does not close

    def test_a_page_without_headings_has_an_empty_outline(self):
        self.assertEqual(outline("Just text.\n\nMore text.\n"), [])
        self.assertEqual(outline(""), [])

    def test_the_title_is_plain_text(self):
        self.assertEqual(plain_title("A **bold** [link](http://x.test) and `code` and \\* star"), "A bold link and code and * star")
        self.assertEqual(plain_title("![image](a.png) Title"), "image Title")
        self.assertEqual(plain_title("snake_case_name stays"), "snake_case_name stays")
        self.assertEqual(outline("## 1\\. Validate input ##\n")[0].title, "1. Validate input")


class SectionTest(unittest.TestCase):
    def test_a_section_runs_to_the_next_heading_of_the_same_or_a_higher_level(self):
        text, heading = extract_section(PAGE, "Steps")
        self.assertEqual(heading.title, "Steps")
        self.assertTrue(text.startswith("## Steps\n"))
        self.assertIn("### Texts to copy", text)  # its sub-section is part of it
        self.assertNotIn("Recommended members", text)
        self.assertNotIn("Prerequisites", text)
        self.assertTrue(text.endswith("\n") and not text.endswith("\n\n"))

    def test_a_sub_section_alone(self):
        text, heading = extract_section(PAGE, "texts to copy")
        self.assertEqual((heading.level, text), (3, "### Texts to copy\n\nSome text.\n"))

    def test_the_last_section_runs_to_the_end(self):
        self.assertEqual(extract_section(PAGE, "recommended")[0], "## Recommended members\n\nThe product owner.\n")

    def test_the_heading_is_found_by_its_text_a_part_of_it_or_its_number(self):
        for selector in ("Steps", "steps", "  STEPS  ", "Steps:", "3", "ste"):
            with self.subTest(selector=selector):
                self.assertEqual(extract_section(PAGE, selector)[1].title, "Steps")

    def test_a_code_block_stays_whole_in_its_section(self):
        text, _ = extract_section(PAGE, "Prerequisites")
        self.assertIn("```bash\n# not a heading\nconfig set X\n```", text)

    def test_a_heading_that_is_a_number_is_found_by_its_text_before_its_position(self):
        page = "# Intro\n\nx\n\n## 2\n\ntwo\n\n## Other\n\ny\n"
        self.assertEqual(extract_section(page, "2")[1].title, "2")

    def test_no_such_heading_lists_the_headings(self):
        with self.assertRaises(ValidationError) as caught:
            extract_section(PAGE, "nothing")
        self.assertIn("1. Background", caught.exception.hint)
        self.assertIn("5. Recommended members", caught.exception.hint)

    def test_an_ambiguous_heading_asks_for_a_number(self):
        with self.assertRaises(ValidationError) as caught:
            extract_section(PAGE, "s")
        self.assertIn("match", caught.exception.message)
        self.assertIn("3. Steps", caught.exception.hint)

    def test_the_same_heading_twice_asks_for_a_number_and_the_number_works(self):
        page = "# A\n\n## Purpose\n\nfirst\n\n# B\n\n## Purpose\n\nsecond\n"
        with self.assertRaises(ValidationError):
            extract_section(page, "Purpose")
        self.assertEqual(extract_section(page, "4")[0], "## Purpose\n\nsecond\n")

    def test_a_page_without_headings_and_an_empty_selector_are_explained(self):
        with self.assertRaises(ValidationError) as caught:
            extract_section("Just text.\n", "x")
        self.assertIn("no headings", caught.exception.message)
        for selector in ("", "   ", "**"):
            with self.subTest(selector=selector):
                with self.assertRaises(ValidationError):
                    extract_section(PAGE, selector)


class TruncateTest(unittest.TestCase):
    def test_a_text_that_fits_is_not_touched(self):
        self.assertEqual(truncate(PAGE, len(PAGE)), (PAGE, False))
        self.assertEqual(truncate(PAGE, 0), (PAGE, False))
        self.assertEqual(truncate(PAGE, -5), (PAGE, False))

    def test_the_cut_is_at_the_end_of_a_paragraph_and_within_the_limit(self):
        for limit in (60, 130, 200, len(PAGE) - 30):
            with self.subTest(limit=limit):
                cut, flag = truncate(PAGE, limit)
                self.assertTrue(flag)
                self.assertLessEqual(len(cut), limit + 1)
                self.assertTrue(PAGE.startswith(cut.rstrip()))
                self.assertTrue(cut.endswith("\n"))

    def test_a_code_block_is_never_cut_in_the_middle(self):
        start = PAGE.index("```bash")
        for limit in range(start + 4, start + 40, 6):
            cut, _ = truncate(PAGE, limit)
            self.assertEqual(cut.count("```") % 2, 0, (limit, cut))

    def test_a_code_block_that_follows_at_once_is_left_out_not_cut(self):
        text = "Intro line.\n```\n" + "code line\n" * 50 + "```\n"
        cut, flag = truncate(text, 80)
        self.assertEqual((cut, flag), ("Intro line.\n", True))
        self.assertEqual(cut.count("```") % 2, 0)

    def test_the_cut_does_not_end_with_a_heading_that_has_nothing_below_it(self):
        for limit in range(30, len(PAGE), 7):  # below a line's length even a hard cut has to cut the line
            cut, flag = truncate(PAGE, limit)
            if flag and cut.strip():
                self.assertFalse(cut.rstrip().splitlines()[-1].startswith("#"), (limit, cut))

    def test_a_first_paragraph_longer_than_the_limit_is_cut_at_a_word(self):
        cut, flag = truncate("Word " * 100, 50)
        self.assertTrue(flag)
        self.assertLessEqual(len(cut), 51)
        self.assertTrue(cut.rstrip().endswith("Word"))

    def test_one_endless_line_is_cut_hard(self):
        cut, flag = truncate("x" * 500, 100)
        self.assertEqual((len(cut), flag), (101, True))

    def test_the_text_is_never_longer_than_the_limit_even_when_nothing_fits_whole(self):
        fence = "`" * 3
        for text in ("# H\nlong body\n", f"{fence}\n" + "x" * 100 + f"\n{fence}\n", PAGE, "Word " * 100):
            for limit in range(1, min(len(text), 120)):
                with self.subTest(limit=limit, start=text[:6]):
                    cut, flag = truncate(text, limit)
                    self.assertTrue(flag)
                    self.assertLessEqual(len(cut.rstrip("\n")), limit)


if __name__ == "__main__":
    unittest.main()
