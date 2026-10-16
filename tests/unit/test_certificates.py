"""Reading the names out of a certificate that a server presented, for an error message."""
import random
import ssl
import unittest

from conflu_c_cli.domain.certificates import _clean, certificate_names, untrusted_chain_note
from tests.support.public_certificates import AMAZON_ROOT_CA_1, CROSS_SIGNED, INTERMEDIATE

ROOT = ssl.PEM_cert_to_DER_cert(AMAZON_ROOT_CA_1)
CROSS = ssl.PEM_cert_to_DER_cert(CROSS_SIGNED)
MIDDLE = ssl.PEM_cert_to_DER_cert(INTERMEDIATE)
STARFIELD = "Starfield Services Root Certificate Authority - G2"


class NamesTest(unittest.TestCase):
    def test_a_root_is_its_own_issuer(self):
        names = certificate_names(ROOT)
        self.assertEqual((names.subject, names.issuer, names.self_signed), ("Amazon Root CA 1", "Amazon Root CA 1", True))

    def test_an_intermediate_names_the_authority_above_it(self):
        names = certificate_names(MIDDLE)
        self.assertEqual((names.subject, names.issuer, names.self_signed), ("Amazon RSA 2048 M04", "Amazon Root CA 1", False))

    def test_a_cross_signed_root_has_the_same_name_and_another_issuer(self):
        names = certificate_names(CROSS)
        self.assertEqual((names.subject, names.issuer, names.self_signed), ("Amazon Root CA 1", STARFIELD, False))

    def test_what_cannot_be_read_gives_nothing_and_never_raises(self):
        for data in (b"", b"\x30", b"\x30\x82", b"\x30\x84\xff\xff\xff\xff", b"not a certificate", bytes(100), b"\x30\x03\x02\x01\x00"):
            with self.subTest(data=data[:12]):
                self.assertIsNone(certificate_names(data))
        self.assertEqual(untrusted_chain_note([b"", b"junk"]), "")
        self.assertEqual(untrusted_chain_note([]), "")

    def test_a_certificate_cut_short_or_damaged_anywhere_never_raises(self):
        for length in range(0, len(MIDDLE), 7):
            certificate_names(MIDDLE[:length])
        generator = random.Random(20261015)
        for _ in range(400):
            damaged = bytearray(MIDDLE)
            for _ in range(generator.randint(1, 6)):
                damaged[generator.randrange(len(damaged))] = generator.randrange(256)
            result = certificate_names(bytes(damaged))
            self.assertTrue(result is None or isinstance(result.subject, str))

    def test_names_that_try_to_drive_a_terminal_are_made_harmless(self):
        old = b"Amazon Root CA 1"
        assert MIDDLE.count(old) == 1  # the issuer; the subject is "Amazon RSA 2048 M04"
        hostile = "\x1b]0;owned\x07\x9b2J!!".encode("latin-1")[: len(old)].ljust(len(old), b"x")
        names = certificate_names(MIDDLE.replace(old, hostile))
        self.assertTrue(names.issuer.isprintable())
        self.assertNotIn("\x1b", names.issuer + names.subject)
        self.assertNotIn("\x9b", names.issuer + names.subject)

    def test_a_long_name_is_cut_short_and_odd_characters_become_spaces(self):
        cleaned = _clean("A" * 500)
        self.assertEqual((len(cleaned), cleaned[-3:]), (80, "..."))
        self.assertEqual(_clean("A" * 80), "A" * 80)  # exactly the limit is left alone
        self.assertEqual(_clean("a\x1b[2Jb\x07  c\n\td\u2028e\u200bf"), "a [2Jb c d e f")
        self.assertEqual(_clean("Gr\u00fc\u00dfe \u65e5\u672c\u8a9e"), "Gr\u00fc\u00dfe \u65e5\u672c\u8a9e")  # real names keep their letters


class NoteTest(unittest.TestCase):
    def test_a_chain_is_told_from_the_certificate_up_to_the_authority_that_vouches_for_it(self):
        note = untrusted_chain_note([MIDDLE, CROSS])
        self.assertEqual(
            note,
            "The server presented this chain, from its own certificate up to the authority that vouches for it: "
            f"'Amazon RSA 2048 M04' <- 'Amazon Root CA 1' <- '{STARFIELD}' (not sent by the server).",
        )

    def test_a_chain_that_ends_in_a_root_does_not_name_a_missing_issuer(self):
        note = untrusted_chain_note([MIDDLE, ROOT])
        self.assertTrue(note.endswith("'Amazon RSA 2048 M04' <- 'Amazon Root CA 1'."))
        self.assertNotIn("not sent", note)

    def test_a_server_that_sends_only_its_own_certificate_still_gets_its_issuer_named(self):
        self.assertIn("'Amazon RSA 2048 M04' <- 'Amazon Root CA 1' (not sent by the server)", untrusted_chain_note([MIDDLE]))

    def test_a_chain_of_thousands_is_cut_short(self):
        note = untrusted_chain_note([MIDDLE] * 5000)
        self.assertLess(note.count("<-"), 12)

    def test_unreadable_certificates_in_the_middle_are_skipped(self):
        self.assertIn("'Amazon Root CA 1'", untrusted_chain_note([MIDDLE, b"junk", ROOT]))


if __name__ == "__main__":
    unittest.main()
