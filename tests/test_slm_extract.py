import unittest

from crawler import slm_extract as extract
from crawler.model_contract import validate_extraction


class FakeCache:
    model = "fake"

    def __init__(self, parsed):
        self.parsed = parsed

    def get(self, sentence):
        return {"parsed": self.parsed, "valid": True}


VOCAB = {("hoàng", "thùy", "linh"): ("Hoàng Thùy Linh", "Person"), ("see", "tình"): ("See Tình", "Song"), ("tiên", "cookie"): ("Tiên Cookie", "Person")}
TEXT = "Mở bài.\nCa khúc See Tình do Hoàng Thùy Linh trình bày, Tiên Cookie sáng tác, gây sốt mạng xã hội."


class ExtractTest(unittest.TestCase):
    def run_doc(self, parsed):
        return extract.extract_document("D1", TEXT, (VOCAB, None, frozenset()), FakeCache(parsed))

    def test_contract_valid_and_offsets(self):
        res, log = self.run_doc({
            "entities": [{"text": "See Tình", "type": "Song"}, {"text": "Hoàng Thùy Linh", "type": "Person"}, {"text": "Tiên Cookie", "type": "Person"}, {"text": "Sơn Tùng", "type": "Person"}],
            "relations": [
                {"head": "Hoàng Thùy Linh", "type": "PERFORMED", "tail": "See Tình", "evidence": "Hoàng Thùy Linh trình bày"},
                {"head": "Tiên Cookie", "type": "COMPOSED", "tail": "See Tình", "evidence": "Tiên Cookie ... sáng tác"},
                {"head": "See Tình", "type": "PERFORMED", "tail": "Hoàng Thùy Linh", "evidence": "x"},
            ],
        })
        self.assertEqual(validate_extraction(res, {"D1": TEXT}), [])
        for e in res["entities"]:
            self.assertEqual(TEXT[e["start"] : e["end"]], e["text"])
        self.assertEqual([r["confidence"] for r in res["relations"]], [extract.CONFIDENCE_VERBATIM, extract.CONFIDENCE_REPAIRED])
        self.assertEqual(sorted(x["kind"] for x in log), ["mention", "relation"])

    def test_looping_sentence_is_logged_not_fatal(self):
        class LoopCache(FakeCache):
            def get(self, sentence):
                return {"parsed": {"entities": [], "relations": []}, "valid": False, "done_reason": "length"}

        res, log = extract.extract_document("D1", TEXT, (VOCAB, None, frozenset()), LoopCache(None))
        self.assertEqual((res["entities"], res["relations"]), ([], []))
        self.assertEqual([(x["kind"], x["reason"]) for x in log], [("sentence", "SLM lặp, chạm giới hạn token đầu ra")])

    def test_case_insensitive_locate(self):
        self.assertEqual(extract.locate("Ca sĩ HOÀNG THÙY LINH hát", "Hoàng Thùy Linh"), (6, 21))
        self.assertIsNone(extract.locate("Ca sĩ hát", "Erik"))


if __name__ == "__main__":
    unittest.main()
