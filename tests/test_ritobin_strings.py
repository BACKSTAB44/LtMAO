from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from LtMAO.ritobin import Reader, clean_escapes, make_escapes


class RitobinStringEscapingTests(unittest.TestCase):
    def test_trailing_backslash_is_escaped(self):
        self.assertEqual(make_escapes("soft back\\"), "soft back\\\\")
    
    def test_escape_and_unescape_round_trip(self):
        samples = [
            "soft back\\",
            "folder\\file",
            r"\n",
            'quoted " text and a trailing slash\\',
            "\n\t\r\a\b\f",
            "control:\x01",
        ]
        for sample in samples:
            with self.subTest(sample=repr(sample)):
                self.assertEqual(clean_escapes(make_escapes(sample)), sample)

    def test_reader_accepts_closing_quote_after_escaped_trailing_backslash(self):
        sample = "soft back\\"
        quoted = '"' + make_escapes(sample) + '"'
        reader = Reader(quoted)

        self.assertEqual(reader.read_quote(), sample)
        self.assertEqual(reader.cur, len(quoted))

    def test_reader_handles_escaped_quotes_and_backslashes_together(self):
        sample = 'say "hello" from C:\\temp\\'
        quoted = '"' + make_escapes(sample) + '"'
        reader = Reader(quoted)

        self.assertEqual(reader.read_quote(), sample)
        self.assertEqual(reader.cur, len(quoted))


if __name__ == "__main__":
    unittest.main()
