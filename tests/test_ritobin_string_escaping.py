import sys
import unittest
from pathlib import Path

# LtMAO keeps its Python package under src/ rather than at the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from LtMAO.ritobin import Reader, make_escapes


class RitobinStringEscapingTests(unittest.TestCase):
    def test_trailing_backslash_is_escaped(self):
        self.assertEqual(make_escapes("soft back\\"), "soft back\\\\")

    def test_quoted_string_round_trips_trailing_backslash(self):
        original = "soft back\\"
        encoded = '"' + make_escapes(original) + '"'

        reader = Reader(encoded)
        self.assertEqual(reader.read_quote(), original)
        self.assertEqual(reader.cur, len(encoded))

    def test_quoted_strings_round_trip_backslashes_and_quotes(self):
        values = (
            "soft back\\",
            r"literal \n",
            "actual\nnewline",
            'embedded " quote',
            "two slashes \\\\",
            r'slash before quote \"',
        )

        for original in values:
            with self.subTest(original=original):
                encoded = '"' + make_escapes(original) + '"'
                reader = Reader(encoded)
                self.assertEqual(reader.read_quote(), original)
                self.assertEqual(reader.cur, len(encoded))


if __name__ == "__main__":
    unittest.main()
