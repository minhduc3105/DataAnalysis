import unittest

import pandas as pd

from crawler import gold_eval


def relations(rows):
    return pd.DataFrame(rows, columns=["gold_id", "relation_type", "platform", "label_huy", "correct_relation_type", "note"])


class WilsonTest(unittest.TestCase):
    def test_three_of_four(self):
        self.assertEqual(gold_eval.wilson(3, 4), (0.3006, 0.9544))

    def test_empty(self):
        self.assertEqual(gold_eval.wilson(0, 0), (0.0, 0.0))


class PrecisionTest(unittest.TestCase):
    def setUp(self):
        self.df = relations([
            ["G1", "A", "YouTube", "đúng", "", ""],
            ["G2", "A", "YouTube", "đúng", "", ""],
            ["G3", "A", "YouTube", "đúng", "", ""],
            ["G4", "A", "YouTube", "sai", "NONE", "ten_rac"],
            ["G5", "B", "Spotify", "đúng", "", ""],
            ["G6", "B", "Spotify", "sai", "FEATURED_ON", "sai_loai: là khách feat."],
            ["G7", "B", "Spotify", "không rõ", "", "khong_xac_minh"],
        ])
        self.table, self.summary = gold_eval.precision_by_type(self.df, {"A": 300, "B": 100})

    def test_per_type(self):
        a = self.table.set_index("relation_type").loc["A"]
        b = self.table.set_index("relation_type").loc["B"]
        self.assertEqual((a.correct, a.wrong, a.unclear, a.precision), (3, 1, 0, 0.75))
        self.assertEqual((b.correct, b.wrong, b.unclear, b.precision), (1, 1, 1, 0.5))
        self.assertEqual(b.precision_unclear_as_wrong, 0.3333)

    def test_summary(self):
        self.assertEqual(self.summary["precision_micro"], 0.6667)
        self.assertEqual(self.summary["precision_weighted"], 0.6875)
        self.assertEqual(self.summary["precision_weighted_ci95"], (0.3251, 1.0))
        self.assertEqual(self.summary["precision_unclear_as_wrong"], 0.5714)
        self.assertEqual(self.summary["unclear"], 1)

    def test_error_codes_strip_detail(self):
        counts = gold_eval.error_table(self.df).set_index("code")["count"].to_dict()
        self.assertEqual(counts, {"ten_rac": 1, "sai_loai": 1, "khong_xac_minh": 1})

    def test_checks_pass(self):
        self.assertEqual(gold_eval.check_relations(self.df), [])


class RelationCheckTest(unittest.TestCase):
    def test_bad_rows(self):
        df = relations([
            ["G1", "A", "", "Đúng", "", ""],
            ["G2", "A", "", "sai", "ARRAGER", "sai_loai"],
            ["G3", "A", "", "sai", "NONE", "tên rác"],
            ["G4", "A", "", "đúng", "PRODUCED", ""],
        ])
        errors = gold_eval.check_relations(df)
        self.assertEqual(len(errors), 4)
        self.assertTrue(errors[1].startswith("G2") and "ARRAGER" in errors[1])


class SentenceCheckTest(unittest.TestCase):
    def check(self, sentence, ents, rels):
        df = pd.DataFrame([{"gold_id": "S1", "sentence": sentence, "entities_huy": ents, "relations_huy": rels}])
        return gold_eval.check_sentences(df)

    def test_valid(self):
        self.assertEqual(self.check("Ca khúc See Tình do Hoàng Thùy Linh trình bày.", "See Tình|Song; HOÀNG THÙY LINH|Person", "Hoàng Thùy Linh|PERFORMED|See Tình"), [])

    def test_none(self):
        self.assertEqual(self.check("Một câu không có ai.", "NONE", "NONE"), [])

    def test_undirected_any_order(self):
        self.assertEqual(self.check("Da LAB tranh chấp với công ty X Music.", "Da LAB|Group; X Music|Company", "X Music|DISPUTED_WITH|Da LAB"), [])

    def test_errors(self):
        self.assertEqual(len(self.check("A hát bài B.", "Z|Singer", "NONE")), 2)
        self.assertIn("không có trong entities_huy", self.check("A hát bài B.", "A|Person; B|Song", "C|PERFORMED|B")[0])
        self.assertIn("sai kiểu nút", self.check("A hát bài B.", "A|Person; B|Song", "B|PERFORMED|A")[0])
        self.assertIn("sai cú pháp", self.check("A hát bài B.", "", "NONE")[0])


class SplitTest(unittest.TestCase):
    def setUp(self):
        rows = [{"gold_id": f"S{i:02d}", "document_id": f"D{i:02d}", "sentence": f"câu số {i} về nghệ sĩ thứ {i}", "relations_huy": "A|PERFORMED|B" if i < 10 else "NONE"} for i in range(30)]
        rows[25]["sentence"] = "Đức Phúc vui vẻ chụp hình kỉ niệm cùng Erik"
        self.df = pd.DataFrame(rows)
        self.few_shot = ["Đức Phúc vui vẻ chụp hình kỉ niệm cùng Erik sau đêm nhạc."]

    def test_few_shot_forced_into_dev(self):
        out = gold_eval.make_split(self.df, self.few_shot).set_index("gold_id")
        self.assertEqual(out.loc["S25", "split"], "dev")
        self.assertEqual(out.loc["S25", "reason"], "trùng ví dụ few-shot")

    def test_stratified_share(self):
        out = gold_eval.make_split(self.df, self.few_shot)
        dev = out[out.split == "dev"]
        self.assertEqual(int(dev.has_relation.sum()), 3)
        self.assertEqual(int((~dev.has_relation).sum()), 6)

    def test_deterministic(self):
        a = gold_eval.make_split(self.df, self.few_shot)
        b = gold_eval.make_split(self.df, self.few_shot)
        self.assertTrue(a.equals(b))


if __name__ == "__main__":
    unittest.main()
