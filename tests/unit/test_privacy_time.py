"""The redaction runs in a time that grows with the text, not with its square: a hostile page must not freeze the default read path."""
import time
import unittest

from conflu_c_cli.domain.privacy import redact_storage, redact_text, strip_users

LIMIT_SECONDS = 3.0  # the work takes a few hundredths of a second; the old patterns took minutes for these sizes


def seconds(call, *args) -> float:
    started = time.perf_counter()
    call(*args)
    return time.perf_counter() - started


class RedactionTimeTest(unittest.TestCase):
    def test_one_long_word_is_read_once(self):
        for text in ("a" * 400_000, "a." * 200_000, "a-" * 200_000, "a+" * 200_000, "a@" * 100_000, "a'" * 200_000, "a&" * 200_000, "'" * 400_000, "!#$%*^`{|}~" * 40_000):
            with self.subTest(shape=text[:6], size=len(text)):
                self.assertLess(seconds(redact_text, text), LIMIT_SECONDS)

    def test_a_text_of_nothing_but_addresses_is_read_once(self):
        for text in ("http://" * 150_000, "https://a/" * 80_000, "/wiki/people/" * 60_000, "[x](http://" * 60_000):
            with self.subTest(shape=text[:12], size=len(text)):
                self.assertLess(seconds(redact_text, text), LIMIT_SECONDS)

    def test_a_page_body_and_raw_json_of_a_long_word_are_read_once(self):
        body = "<p>" + "a" * 400_000 + "</p>"
        self.assertLess(seconds(redact_storage, body), LIMIT_SECONDS)
        self.assertLess(seconds(strip_users, {"body": {"storage": {"value": body}}, "title": "a" * 400_000}), LIMIT_SECONDS)


class RedactionStillRedactsTest(unittest.TestCase):
    def test_what_was_redacted_before_is_redacted_now(self):
        cases = {
            "write to alex@example.com now": "write to [email] now",
            "alex.o'neil+tag@sub.example.co.uk": "[email]",  # the apostrophe belongs to the local part, which people really have (o'connor)
            "maria.o'connor@example.com wrote": "[email] wrote",
            "a&b@example.com and tom!x@example.com": "[email] and [email]",
            "quoted 'alex@example.com' here": "quoted [email]' here",  # a leading quote is taken for part of the address: safer to lose it than to keep a first name
            "a.b-c_d+e@f-g.example": "[email]",
            "(x@y.example)": "([email])",
            "two a@b.example and c@d.example": "two [email] and [email]",
            "no address @ here, nor a@b": "no address @ here, nor a@b",
            "see https://example.atlassian.net/wiki/people/5b10ac8d82e05b22cc7d4ef5 please": "see [personal link] please",
            "see https://example.atlassian.net/wiki/spaces/~5b10ac8d82e05b22cc7d4ef5/overview": "see [personal link]",
            "[Alex](https://example.atlassian.net/wiki/people/5b10ac8d82e05b22cc7d4ef5) wrote": "[personal link] wrote",
            "a path docs/people/roles is no profile": "a path docs/people/roles is no profile",
            "https://example.atlassian.net/wiki/spaces/ENG/overview stays": "https://example.atlassian.net/wiki/spaces/ENG/overview stays",
            "/wiki/people/abc inside text": "[personal link] inside text",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(redact_text(text), expected)

    def test_an_address_inside_an_address_leaves_the_outer_text_alone(self):
        text = "http://a.example/redirect?to=https://example.atlassian.net/wiki/people/5b10ac8d82e05b22cc7d4ef5"
        self.assertNotIn("5b10ac8d82e05b22cc7d4ef5", redact_text(text))

    def test_a_link_to_a_profile_goes_with_its_text_even_when_the_text_has_escaped_brackets(self):
        link = "https://example.atlassian.net/wiki/people/5b10ac8d82e05b22cc7d4ef5"
        cases = {
            f"[a\\[b]({link}) tail": "[personal link] tail",
            f"[Alex \\\\](/wiki/people/5b10ac8d82e05b22cc7d4ef5) x": "[personal link] x",
            f"[x [y]({link})": "[x [personal link]",  # an unescaped [ ends the text of the link
            f"[x\ny]({link})": "[x\ny]([personal link])",  # a line break does too: only the address goes
            f"see [text]({link}) and [more]({link})": "see [personal link] and [personal link]",
            f"[no closing paren]({link}": "[no closing paren]([personal link]",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(redact_text(text), expected)

    def test_escaped_brackets_and_a_profile_path_in_a_long_text_are_read_once(self):
        link = " https://example.atlassian.net/wiki/people/5b10ac8d82e05b22cc7d4ef5"
        for text in ("\\[a" * 150_000 + link, "[a" * 200_000 + link, "](" * 150_000 + link, "[" + "x" * 200_000 + "](" + link.strip() + ")"):
            with self.subTest(shape=text[:6], size=len(text)):
                self.assertLess(seconds(redact_text, text), LIMIT_SECONDS)


if __name__ == "__main__":
    unittest.main()
