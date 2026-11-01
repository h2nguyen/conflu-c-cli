"""The attributes that name a person in storage format are blanked however they are written: single or double quotes, blanks around the `=`, any case."""
import time
import unittest

from conflu_c_cli.domain.privacy import has_blanked_mentions, mentions_people, redact_storage

ACCOUNT = "5b10ac8d82e05b22cc7d4ef5"
LIMIT_SECONDS = 3.0


class AttributeFormsTest(unittest.TestCase):
    def test_every_way_to_write_an_attribute_is_blanked(self):
        cases = {
            f"<ri:user ri:account-id='{ACCOUNT}'/>": '<ri:user ri:account-id="hidden"/>',
            f'<ri:user ri:account-id = "{ACCOUNT}"/>': '<ri:user ri:account-id="hidden"/>',
            f'<ri:user ri:account-id\n=\t"{ACCOUNT}"/>': '<ri:user ri:account-id="hidden"/>',
            f'<span data-account-id="{ACCOUNT}">@x</span>': '<span data-account-id="hidden">@x</span>',
            f"<span data-account-id='{ACCOUNT}'>@x</span>": '<span data-account-id="hidden">@x</span>',
            "<ri:user ri:userkey='8a7f9c'/>": '<ri:user ri:userkey="hidden"/>',
            "<ri:user ri:username='alex.example'/>": '<ri:user ri:username="hidden"/>',
            f'<ri:user RI:ACCOUNT-ID="{ACCOUNT}"/>': '<ri:user RI:ACCOUNT-ID="hidden"/>',
            f"<ri:page ri:space-key='~{ACCOUNT}' ri:content-title='Home'/>": '<ri:page ri:space-key="[hidden]" ri:content-title=\'Home\'/>',
            f'<ri:page ri:space-key = "~{ACCOUNT}"/>': '<ri:page ri:space-key="[hidden]"/>',
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                shown = redact_storage(text)
                self.assertEqual(shown, expected)
                self.assertNotIn(ACCOUNT, shown)

    def test_an_ordinary_space_key_and_other_attributes_stay(self):
        text = "<ri:page ri:space-key='ENG' ri:content-title='Home' data-other='x' title=\"a = b\"/>"
        self.assertEqual(redact_storage(text), text)

    def test_blanked_attributes_are_recognised_in_every_form(self):
        for text in (
            '<ri:user ri:account-id="hidden"/>',
            "<ri:user ri:account-id='hidden'/>",
            '<ri:user ri:account-id = "hidden"/>',
            '<span data-account-id="hidden">@x</span>',
            '<span data-userkey="hidden">@x</span>',
            '<ri:page ri:space-key="[hidden]"/>',
            "<ri:page ri:space-key='[hidden]'/>",
        ):
            with self.subTest(text=text):
                self.assertTrue(has_blanked_mentions(text))
        for text in ('<ri:user ri:account-id="5b10ac8d82e05b22cc7d4ef5"/>', '<ri:page ri:space-key="ENG"/>', "<p>hidden</p>"):
            with self.subTest(text=text):
                self.assertFalse(has_blanked_mentions(text))

    def test_mentions_are_found_in_every_form(self):
        for text in (f"<ri:user ri:account-id='{ACCOUNT}'/>", f'<span data-account-id = "{ACCOUNT}">', "<ri:user ri:username='alex'/>"):
            with self.subTest(text=text):
                self.assertTrue(mentions_people(text))

    def test_a_long_run_of_blanks_after_a_name_is_read_once(self):
        for text in ("ri:account-id" + " " * 400_000 + "x", ("ri:account-id " * 50_000) + "ri:userkey", "data-username =" + " " * 400_000):
            with self.subTest(size=len(text)):
                started = time.perf_counter()
                redact_storage(text)
                has_blanked_mentions(text)
                mentions_people(text)
                self.assertLess(time.perf_counter() - started, LIMIT_SECONDS)


if __name__ == "__main__":
    unittest.main()
