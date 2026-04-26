from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "AI Chatbot Agent")
    environment: str = os.getenv("APP_ENV", "local")

    # Service ports & hosts (đọc từ tên env native của uvicorn/streamlit)
    backend_host: str = os.getenv("UVICORN_HOST", "0.0.0.0")  # noqa: S104
    backend_port: int = int(os.getenv("UVICORN_PORT", "8000"))
    ui_host: str = os.getenv("STREAMLIT_SERVER_ADDRESS", "0.0.0.0")  # noqa: S104
    ui_port: int = int(os.getenv("STREAMLIT_SERVER_PORT", "8501"))
    default_api_url: str = os.getenv("DEFAULT_API_URL", "http://localhost:8000")

    # Logging
    log_format: str = os.getenv("LOG_FORMAT", "")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    api_key_header: str = os.getenv("API_KEY_HEADER", "X-API-Key")
    api_keys: tuple[str, ...] = tuple(
        key.strip() for key in os.getenv("API_KEYS", "").split(",") if key.strip()
    )
    rate_limit_per_minute: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "30"))
    max_message_length: int = int(os.getenv("MAX_MESSAGE_LENGTH", "2000"))
    retrieval_top_k: int = int(os.getenv("RETRIEVAL_TOP_K", "3"))
    max_context_chars: int = int(os.getenv("MAX_CONTEXT_CHARS", "600"))
    chroma_path: str = os.getenv("CHROMA_PATH", "./db/chroma_store")
    chroma_collection: str = os.getenv("CHROMA_COLLECTION", "ai_knowledge")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    embedding_cache_size: int = int(os.getenv("EMBEDDING_CACHE_SIZE", "256"))
    # Hybrid search: kết hợp BM25 (keyword) + Vector (semantic)
    hybrid_search_enabled: bool = os.getenv("HYBRID_SEARCH_ENABLED", "true").lower() == "true"
    bm25_index_path: str = os.getenv("BM25_INDEX_PATH", "./db/bm25_index.pkl")
    # RRF k constant - giá trị nhỏ ưu tiên top results, 60 là default chuẩn
    rrf_k: int = int(os.getenv("RRF_K", "60"))
    # Số chunks lấy từ mỗi nguồn trước khi fuse (cao hơn top_k cuối)
    hybrid_fetch_k: int = int(os.getenv("HYBRID_FETCH_K", "10"))
    # Cross-encoder re-ranker: chấm điểm (query, chunk) chính xác hơn rồi rerank.
    # Default OFF vì cộng 200-500ms; bật khi cần chất lượng cao nhất.
    reranker_enabled: bool = os.getenv("RERANKER_ENABLED", "false").lower() == "true"
    reranker_model: str = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-base")
    # Số chunks lấy từ retriever (vector + BM25 fused) đưa vào reranker.
    # Cao hơn top_k cuối để reranker có nhiều ứng viên để chọn.
    reranker_fetch_k: int = int(os.getenv("RERANKER_FETCH_K", "10"))
    openrouter_base_url: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-exp:free")
    enable_llm_reasoning: bool = os.getenv("ENABLE_LLM_REASONING", "false").lower() == "true"
    max_response_tokens: int = int(os.getenv("MAX_RESPONSE_TOKENS", "400"))
    llm_request_timeout: float = float(os.getenv("LLM_REQUEST_TIMEOUT", "30"))
    answer_cache_ttl: int = int(os.getenv("ANSWER_CACHE_TTL", "3600"))
    answer_cache_size: int = int(os.getenv("ANSWER_CACHE_SIZE", "256"))
    pii_redaction_enabled: bool = os.getenv("PII_REDACTION_ENABLED", "true").lower() == "true"


settings = Settings()
