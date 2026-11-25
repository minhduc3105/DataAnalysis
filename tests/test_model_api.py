import unittest
from unittest import mock

import numpy as np
import requests
from fastapi import HTTPException
from pydantic import ValidationError

from crawler import model_api
from crawler.model_contract import validate_extraction

TEXT = "Mở bài.\nCa khúc See Tình do Hoàng Thùy Linh trình bày, Tiên Cookie sáng tác, gây sốt mạng xã hội."
VOCAB = {("hoàng", "thùy", "linh"): ("Hoàng Thùy Linh", "Person"), ("see", "tình"): ("See Tình", "Song"), ("tiên", "cookie"): ("Tiên Cookie", "Person")}
PARSED = {
    "entities": [{"text": "See Tình", "type": "Song"}, {"text": "Hoàng Thùy Linh", "type": "Person"}],
    "relations": [{"head": "Hoàng Thùy Linh", "type": "PERFORMED", "tail": "See Tình", "evidence": "Hoàng Thùy Linh trình bày"}],
}


class Cache:
    model = "qwen3:8b"

    def __init__(self, out):
        self.out = out

    def get(self, sentence):
        return self.out


class RequestTest(unittest.TestCase):
    def test_contract_rules(self):
        with self.assertRaises(ValidationError):
            model_api.EmbedRequest(schema_version="vn-music-radar.v1", texts=["a"], extra=1)
        with self.assertRaises(ValidationError):
            model_api.EmbedRequest(schema_version="v2", texts=["a"])
        with self.assertRaises(ValidationError):
            model_api.EmbedRequest(schema_version="vn-music-radar.v1", texts=["a"] * (model_api.MAX_TEXTS + 1))
        with self.assertRaises(ValidationError):
            model_api.ExtractRequest(document_id="", schema_version="vn-music-radar.v1", text="x")


@mock.patch.object(model_api, "_require_model", lambda name: None)
class HandlerTest(unittest.TestCase):
    def test_embed_shape_and_blank(self):
        with mock.patch.object(model_api.embedding, "embed", lambda texts: np.ones((len(texts), 1024)) / 32):
            out = model_api.embed(model_api.EmbedRequest(schema_version="vn-music-radar.v1", texts=["a", "b"]))
        self.assertEqual((out["model_version"], out["dimensions"], len(out["vectors"]), len(out["vectors"][0])), ("bge-m3", 1024, 2, 1024))
        self.assertEqual(set(out), {"model_version", "dimensions", "vectors"})
        with self.assertRaises(HTTPException) as ctx:
            model_api.embed(model_api.EmbedRequest(schema_version="vn-music-radar.v1", texts=["a", "  "]))
        self.assertEqual(ctx.exception.status_code, 422)

    def test_extract_valid_contract(self):
        with mock.patch.object(model_api, "_extraction_context", lambda: ((VOCAB, None, frozenset()), Cache({"parsed": PARSED, "valid": True}))):
            out = model_api.extract(model_api.ExtractRequest(document_id="D1", schema_version="vn-music-radar.v1", text=TEXT))
        self.assertEqual(validate_extraction(out, {"D1": TEXT}), [])
        self.assertEqual(len(out["relations"]), 1)

    def test_extract_transient_error_is_503(self):
        failed = {"parsed": {"entities": [], "relations": []}, "valid": False, "error": "ReadTimeout: x"}
        with mock.patch.object(model_api, "_extraction_context", lambda: ((VOCAB, None, frozenset()), Cache(failed))):
            with self.assertRaises(HTTPException) as ctx:
                model_api.extract(model_api.ExtractRequest(document_id="D1", schema_version="vn-music-radar.v1", text=TEXT))
        self.assertEqual(ctx.exception.status_code, 503)


class OllamaDownTest(unittest.TestCase):
    def test_clear_message(self):
        with mock.patch.object(model_api.requests, "get", side_effect=requests.ConnectionError()):
            with self.assertRaises(HTTPException) as ctx:
                model_api._ollama_models()
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertIn("ollama serve", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()
