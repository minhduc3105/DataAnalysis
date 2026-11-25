import unittest

import pandas as pd

from crawler import embedding


class AliasPairsTest(unittest.TestCase):
    def test_skips_case_and_diacritic_variants(self):
        df = pd.DataFrame([
            {"entity_id": "P1", "canonical_name": "Sơn Tùng M-TP", "aliases": "SƠN TÙNG M-TP | Son Tung M-TP | Nguyễn Thanh Tùng"},
            {"entity_id": "P2", "canonical_name": "Đen Vâu", "aliases": ""},
        ])
        self.assertEqual(embedding.alias_pairs(df), [("P1", "Sơn Tùng M-TP", "Nguyễn Thanh Tùng")])

    def test_clean_keeps_diacritics(self):
        self.assertEqual(embedding.clean("  Hoàng   Thùy Linh\n"), "Hoàng Thùy Linh")


if __name__ == "__main__":
    unittest.main()
