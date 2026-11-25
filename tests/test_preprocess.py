import unittest

from crawler import gold, preprocess


def sentences(text):
    return [s for _, _, s in preprocess.split_sentences(text)]


class SplitTest(unittest.TestCase):
    def test_offsets_roundtrip(self):
        text = "  Câu một.  Câu hai!\nTiêu đề\n\nCâu ba "
        for s, e, sent in preprocess.split_sentences(text):
            self.assertEqual(text[s:e], sent)
        self.assertEqual(sentences(text), ["Câu một.", "Câu hai!", "Tiêu đề", "Câu ba"])

    def test_abbreviations_and_initials(self):
        self.assertEqual(len(sentences("Đêm nhạc diễn ra tại TP. HCM vào tối qua. Khán giả rất đông.")), 2)
        self.assertEqual(len(sentences("Bài viết của ThS. Nguyễn Văn A về nhạc Việt.")), 1)
        self.assertEqual(len(sentences("Rapper Quân A.P. Nguyễn phát hành bài mới.")), 1)

    def test_decimal_and_lowercase_continuation(self):
        self.assertEqual(len(sentences("MV đạt 3.5 triệu lượt xem... và vẫn tăng.")), 1)

    def test_quotes_keep_ellipsis_inside(self):
        text = "Cô nói: “Tôi đã cố gắng... Rất nhiều.” Sau đó cô rời đi."
        self.assertEqual(sentences(text), ["Cô nói: “Tôi đã cố gắng... Rất nhiều.”", "Sau đó cô rời đi."])

    def test_long_quote_splits_at_full_stop(self):
        self.assertEqual(len(sentences("Anh nói: “Tôi rất vui. Cảm ơn mọi người.” Rồi anh đi.")), 3)

    def test_missing_space_after_period(self):
        self.assertEqual(sentences("Đến với bạn bè quốc tế.Và Phú Quý rất đẹp."), ["Đến với bạn bè quốc tế.", "Và Phú Quý rất đẹp."])
        self.assertEqual(len(sentences("Sự kiện ở TP.HCM, xem tại Zing.vn và v.v.")), 1)


class MentionTest(unittest.TestCase):
    vocab = {("sơn", "tùng", "m", "tp"): ("Sơn Tùng M-TP", "Person"), ("chúng", "ta", "của", "hiện", "tại"): ("Chúng Ta Của Hiện Tại", "Song")}

    def test_spans_point_into_document(self):
        text = "Mở đầu bài.\nCa khúc Chúng Ta Của Hiện Tại của Sơn Tùng M-TP gây sốt suốt nhiều tuần liền."
        sents, ments = preprocess.preprocess_document("D1", text, self.vocab)
        self.assertEqual([m["text"] for m in ments], ["Chúng Ta Của Hiện Tại", "Sơn Tùng M-TP"])
        for m in ments:
            self.assertEqual(text[m["start"] : m["end"]], m["text"])
        self.assertEqual([s["is_candidate"] for s in sents], [False, True])
        self.assertEqual(len({m["mention_id"] for m in ments}), 2)

    def test_filter_common_words_and_punctuation(self):
        vocab = {**self.vocab, ("trong",): ("STRONG TRỌNG HIẾU", "Person"), ("anh", "tú"): ("Anh Tú", "Person"), ("anh", "tú", "nguyễn"): ("Anh Tú Nguyễn", "Person")}
        common = preprocess.common_words(["Trong đêm nhạc, trong khán phòng, trong tim."], vocab)
        self.assertEqual(common, {"trong"})
        _, ments = preprocess.preprocess_document("D1", "Trong MV mới, Anh Tú (Nguyễn Văn A) hát.", vocab, preprocess.mention_filter(common))
        self.assertEqual([m["text"] for m in ments], ["Anh Tú"])

    def test_stylized_lowercase_names(self):
        import pandas as pd
        vocab = {("tlinh",): ("TLINH", "Person"), ("hiếu", "thứ", "hai"): ("HIEUTHUHAI", "Person"), ("khang",): ("Khang", "Person"), ("lucky",): ("Lucky Girl", "Song")}
        entities = pd.DataFrame([{"entity_type": "Person", "canonical_name": "TLINH", "aliases": "TLinh | tlinh"}, {"entity_type": "Person", "canonical_name": "Hiếu Thứ Hai", "aliases": "hiếu thứ hai"}, {"entity_type": "Person", "canonical_name": "Khang", "aliases": "khang"}, {"entity_type": "Song", "canonical_name": "Lucky Girl", "aliases": "lucky"}])
        allow = preprocess.stylized_lower(entities, vocab)
        self.assertEqual(allow, frozenset({("tlinh",)}))
        self.assertEqual(preprocess.common_words(["tlinh hát, tlinh nhảy"], vocab, allow), set())
        _, ments = preprocess.preprocess_document("D1", "Bài mới của tlinh gây sốt.", vocab, None, allow)
        self.assertEqual([m["text"] for m in ments], ["tlinh"])

    def test_matches_unchanged(self):
        self.assertEqual(gold._matches("anh Sơn Tùng M-TP hát", self.vocab), [("Sơn Tùng M-TP", "Person")])


if __name__ == "__main__":
    unittest.main()
