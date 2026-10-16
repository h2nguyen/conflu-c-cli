"""What a person or an agent types into a search becomes words and phrases."""
import unittest

from conflu_c_cli.domain.searchterms import MAX_TERMS, STOP_WORDS, Term, parse_terms, terms_from_cql


def shown(text):
    result = parse_terms(text)
    return [term.display for term in result.used], list(result.ignored)


class ParseTermsTest(unittest.TestCase):
    def test_a_question_becomes_its_meaningful_words_and_says_what_it_left_out(self):
        self.assertEqual(shown("how do I request an SSO group for QA?"), (["request", "SSO", "group", "QA"], ["how", "do", "I", "an", "for"]))

    def test_the_same_in_german(self):
        self.assertEqual(shown("wie kann ich eine SSO-Gruppe fuer QA beantragen"), (["SSO-Gruppe", "QA", "beantragen"], ["wie", "kann", "ich", "eine", "fuer"]))

    def test_a_phrase_in_quotes_stays_together_also_in_typographic_quotes(self):
        for text in ('"SSO group" QA', "\u201eSSO group\u201c QA", "\u201cSSO group\u201d QA"):
            with self.subTest(text=text):
                result = parse_terms(text)
                self.assertEqual([(term.text, term.phrase) for term in result.used], [("SSO group", True), ("QA", False)])
        self.assertEqual(Term("SSO group", True).display, '"SSO group"')

    def test_punctuation_at_the_end_of_a_word_is_not_part_of_it(self):
        self.assertEqual(shown("QA? roles, (groups) v0.1.0. [TO CLARIFY]"), (["QA", "roles", "groups", "v0.1.0", "TO", "CLARIFY"], []))

    def test_punctuation_inside_a_word_stays(self):
        self.assertEqual(shown("src/load run_id e-mail C# what's"), (["src/load", "run_id", "e-mail", "C#", "what's"], []))

    def test_wildcards_stay_and_a_lone_symbol_is_no_term(self):
        self.assertEqual(shown("rol* *rule = - ! ?"), (["rol*", "*rule"], []))

    def test_abbreviations_in_capitals_are_not_filler_but_the_pronouns_are(self):
        self.assertEqual(shown("IT department and the US team"), (["IT", "department", "US", "team"], ["and", "the"]))
        self.assertEqual(shown("it is for us"), (["it", "is", "for", "us"], []))  # only filler: kept, there is nothing else

    def test_a_quoted_word_is_kept_although_it_is_filler(self):
        self.assertEqual(shown('"how" do I'), (["how"], ["do", "I"]))

    def test_operators_are_never_terms_in_any_spelling(self):
        self.assertEqual(shown("foo AND bar or baz NOT qux"), (["foo", "bar", "baz", "qux"], ["AND", "or", "NOT"]))

    def test_a_text_of_filler_words_only_is_searched_as_it_is(self):
        self.assertEqual(shown("how to"), (["how", "to"], []))

    def test_nothing_gives_no_terms(self):
        for text in ("", "   ", "?!", "= - =", '""', None):
            with self.subTest(text=text):
                self.assertEqual(shown(text), ([], []))

    def test_a_word_is_used_once_whatever_its_case(self):
        self.assertEqual(shown("Roles roles ROLES role"), (["Roles", "role"], []))

    def test_the_number_of_terms_is_limited_and_the_rest_is_reported(self):
        words = [f"word{number}" for number in range(MAX_TERMS + 3)]
        result = parse_terms(" ".join(words))
        self.assertEqual(len(result.used), MAX_TERMS)
        self.assertEqual(list(result.ignored), words[MAX_TERMS:])

    def test_control_characters_and_quotes_cannot_break_what_follows(self):
        self.assertEqual(shown('x" OR space = "SECRET'), (["x", "space", "SECRET"], ["OR"]))
        self.assertEqual(shown("a\x00b\x1b[2Jc"), (["b", "2Jc"], ["a"]))  # a control character separates words, and `a` is filler

    def test_the_filler_list_has_no_word_that_can_be_the_subject_of_a_search(self):
        for word in ("list", "show", "find", "bin", "war", "man", "get", "role", "group", "rule", "page", "space", "label"):
            with self.subTest(word=word):
                self.assertNotIn(word, STOP_WORDS)

    def test_a_term_is_truthy_when_it_has_terms(self):
        self.assertTrue(parse_terms("a b"))
        self.assertFalse(parse_terms("?"))


class TermsFromCqlTest(unittest.TestCase):
    def test_the_words_of_text_and_title_clauses(self):
        self.assertEqual([t.display for t in terms_from_cql('type = page AND text ~ "request SSO group" AND space = "ENG"')], ["request", "SSO", "group"])
        self.assertEqual([t.display for t in terms_from_cql('title ~ "release notes"')], ["release", "notes"])

    def test_a_phrase_and_an_or_group(self):
        self.assertEqual([t.display for t in terms_from_cql('text ~ "\\"SSO group\\"" AND text ~ "QA"')], ['"SSO group"', "QA"])
        self.assertEqual([t.display for t in terms_from_cql('(text ~ "a1" OR text ~ "b2") AND title ~ "c3 d4"')], ["a1", "b2", "c3", "d4"])

    def test_other_clauses_have_no_words(self):
        self.assertEqual(terms_from_cql('type = page AND label = "adr" AND lastmodified >= "2026-01-01"'), ())
        self.assertEqual(terms_from_cql(""), ())

    def test_a_word_once(self):
        self.assertEqual([t.display for t in terms_from_cql('text ~ "Roles" AND title ~ "roles"')], ["Roles"])


if __name__ == "__main__":
    unittest.main()
