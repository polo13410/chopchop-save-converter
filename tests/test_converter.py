"""Tests. Run from the repository root: python -m unittest discover tests

The conversion test converts examples/demo-save.sav and compares the result
byte for byte with examples/converted-save.sav, the expected output.
"""

import os
import unittest

from chopchop import data_dir, odin_binary
from chopchop.converter import convert

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "examples", "demo-save.sav")
REFERENCE = os.path.join(ROOT, "examples", "converted-save.sav")


class RoundTrip(unittest.TestCase):
    def test_base_save_round_trip(self):
        with open(os.path.join(data_dir(), "base-full-game.sav"), "rb") as f:
            data = f.read()
        self.assertEqual(odin_binary.encode(odin_binary.decode(data)), data)


class Conversion(unittest.TestCase):
    def test_matches_reference(self):
        with open(DEMO, "rb") as f:
            demo = f.read()
        with open(REFERENCE, "rb") as f:
            reference = f.read()
        out = convert(demo, log=lambda msg: None)
        self.assertEqual(out, reference)

    def test_output_reads_back(self):
        with open(DEMO, "rb") as f:
            out = convert(f.read(), log=lambda msg: None)
        doc = odin_binary.decode(out)
        self.assertEqual(odin_binary.encode(doc), out)


if __name__ == "__main__":
    unittest.main()
