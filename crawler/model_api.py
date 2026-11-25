import threading
from typing import Literal

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import embedding, slm_extract
from .model_contract import SCHEMA_VERSION
from .slm import OLLAMA

MAX_TEXTS = 256
EXTRACT_MODEL = slm_extract.MODEL

app = FastAPI(title="VN Music Radar model API", version="v1")
_dictionary_lock = threading.Lock()
_state: dict = {}


class ExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str = Field(min_length=1)
    schema_version: Literal["vn-music-radar.v1"]
    text: str = Field(min_length=1)


class EmbedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["vn-music-radar.v1"]
    texts: list[str] = Field(min_length=1, max_length=MAX_TEXTS)


def _ollama_models() -> set[str]:
    try:
        r = requests.get(f"{OLLAMA}/api/tags", timeout=5)
        r.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(503, f"Ollama chưa chạy ở {OLLAMA} ({type(exc).__name__}); mở Ollama hoặc chạy `ollama serve`") from exc
    names = {m["name"] for m in r.json().get("models", [])}
    return names | {n.removesuffix(":latest") for n in names}


def _require_model(name: str) -> None:
    if name not in _ollama_models():
        raise HTTPException(503, f"Ollama chưa có mô hình {name}; chạy `ollama pull {name}`")


def _extraction_context() -> tuple:
    """Từ điển + danh sách từ thường cần đọc cả kho bài (~10–20 s), nên nạp một lần ở lần /extract đầu tiên."""
    with _dictionary_lock:
        if "ctx" not in _state:
            from .preprocess import load_articles, load_dictionary

            _, everything = load_articles(docs=None)
            vocab, reject, allow_lower, _ = load_dictionary(everything.text)
            _state["ctx"] = (vocab, reject, allow_lower)
            _state["cache"] = slm_extract.SentenceCache(EXTRACT_MODEL)
    return _state["ctx"], _state["cache"]


@app.get("/health")
def health() -> dict:
    models = _ollama_models()
    return {
        "status": "ok" if {EXTRACT_MODEL, embedding.EMBED_MODEL} <= models else "missing_model",
        "schema_version": SCHEMA_VERSION,
        "extract_model_version": slm_extract.model_version(EXTRACT_MODEL),
        "embed_model_version": embedding.EMBED_MODEL,
        "dimensions": embedding.DIMENSIONS,
        "models_ready": {EXTRACT_MODEL: EXTRACT_MODEL in models, embedding.EMBED_MODEL: embedding.EMBED_MODEL in models},
    }


@app.post("/embed")
def embed(req: EmbedRequest) -> dict:
    blank = [i for i, t in enumerate(req.texts) if not t.strip()]
    if blank:
        # Vector của chuỗi rỗng chia cho chuẩn 0 thành NaN, làm hỏng vector index của Neo4j.
        raise HTTPException(422, f"texts[{blank[0]}] rỗng; bỏ chuỗi rỗng trước khi gửi ({len(blank)} chuỗi)")
    _require_model(embedding.EMBED_MODEL)
    try:
        vectors = embedding.embed(req.texts)
    except requests.RequestException as exc:
        raise HTTPException(503, f"Ollama lỗi khi embed: {type(exc).__name__}") from exc
    return {"model_version": embedding.EMBED_MODEL, "dimensions": embedding.DIMENSIONS, "vectors": vectors.tolist()}


@app.post("/extract")
def extract(req: ExtractRequest) -> dict:
    _require_model(EXTRACT_MODEL)
    ctx, cache = _extraction_context()
    result, log = slm_extract.extract_document(req.document_id, req.text, ctx, cache)
    transient = [x for x in log if x.get("retryable")]
    if transient:
        raise HTTPException(503, f"{len(transient)} câu lỗi khi gọi Ollama ({transient[0]['reason'][:80]}); gọi lại sau")
    return result
