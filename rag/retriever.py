from __future__ import annotations

from collections import OrderedDict
from threading import Lock
from typing import Any

import chromadb
from sentence_transformers import SentenceTransformer

from config.settings import settings
from rag.errors import RetrievalError

model = SentenceTransformer(settings.embedding_model)
client = chromadb.PersistentClient(path=settings.chroma_path)
collection = client.get_or_create_collection(settings.chroma_collection)

_embedding_cache: OrderedDict[str, list[float]] = OrderedDict()
_embedding_cache_lock = Lock()


def _encode_cached(text: str) -> list[float]:
    max_size = settings.embedding_cache_size
    with _embedding_cache_lock:
        cached = _embedding_cache.get(text)
        if cached is not None:
            _embedding_cache.move_to_end(text)
            return cached
    vector = model.encode([text])[0].tolist()
    with _embedding_cache_lock:
        _embedding_cache[text] = vector
        _embedding_cache.move_to_end(text)
        while len(_embedding_cache) > max_size:
            _embedding_cache.popitem(last=False)
    return vector


def warmup() -> None:
    """Preload embedding model bằng 1 query dummy để tránh cold-start."""
    try:
        _encode_cached("warmup")
    except Exception:
        pass
TOPIC_KEYWORDS = {
    "docker": [
        "docker",
        "container",
        "containers",
        "image",
        "images",
        "compose",
        "dockerfile",
    ],
    "ronaldo": [
        "ronaldo",
        "cr7",
        "cristiano",
        "bong da",
        "football",
        "soccer",
        "uefa",
        "fifa",
    ],
    "policy": [
        "hoan tien",
        "refund",
        "policy",
        "chinh sach",
        "faq",
    ],
    "ai": [
        "machine learning",
        "ai",
        "model",
        "llm",
        "embedding",
    ],
    "springboot": [
        "spring",
        "spring boot",
        "springboot",
        "java",
        "jpa",
        "hibernate",
        "actuator",
        "restcontroller",
        "spring security",
        "dependency injection",
        "spring data",
        "maven",
        "gradle",
        "bean",
    ],
    "engineering": [
        "python",
        "backend",
        "frontend",
        "api",
        "web development",
        "development",
    ],
    "react": [
        "react",
        "reactjs",
        "react.js",
        "usestate",
        "useeffect",
        "usememo",
        "usereducer",
        "usecontext",
        "jsx",
        "hook",
        "hooks",
        "next.js",
        "nextjs",
        "component",
    ],
    "kubernetes": [
        "kubernetes",
        "k8s",
        "kubectl",
        "pod",
        "pods",
        "deployment",
        "replicaset",
        "statefulset",
        "daemonset",
        "ingress",
        "configmap",
        "configmaps",
        "secret",
        "secrets",
        "namespace",
        "namespaces",
        "persistent volume",
        "pv",
        "pvc",
        "rbac",
        "hpa",
        "autoscale",
        "autoscaling",
        "helm",
        "minikube",
    ],
    "postgresql": [
        "postgres",
        "postgresql",
        "psql",
        "sql",
        "select",
        "join",
        "foreign key",
        "primary key",
        "transaction",
        "rollback",
        "commit",
        "index",
        "indexes",
        "cte",
        "window function",
        "constraint",
        "view",
    ],
}


def infer_topic(query: str) -> str | None:
    lowered = query.lower()
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return topic
    return None


def _query_collection(
    normalized_query: str,
    top_k: int,
    topic: str | None = None,
) -> dict[str, Any]:
    query_embedding = [_encode_cached(normalized_query)]
    query_kwargs: dict[str, Any] = {
        "query_embeddings": query_embedding,
        "n_results": top_k,
        "include": ["documents", "metadatas", "distances"],
    }
    if topic:
        query_kwargs["where"] = {"topic": topic}
    return collection.query(**query_kwargs)


def _vector_retrieve(query: str, top_k: int, topic: str | None) -> list[dict[str, Any]]:
    """Vector search qua Chroma. Nếu có topic, ưu tiên filter; rỗng thì fallback no-filter."""
    if topic:
        results = _query_collection(query, top_k=top_k, topic=topic)
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        dists = results.get("distances", [[]])[0]
        if docs:
            return _build_chunks(docs, metas, dists)

    results = _query_collection(query, top_k=top_k, topic=None)
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]
    return _build_chunks(docs, metas, dists)


def retrieve(query: str, top_k: int = 3, topic: str | None = None) -> list[dict[str, Any]]:
    """
    Tìm chunks liên quan nhất.

    Mặc định dùng hybrid search (BM25 + vector) khi `HYBRID_SEARCH_ENABLED=true`.
    Tắt env để fallback về vector-only mode.
    """
    normalized_query = query.strip()
    if not normalized_query:
        raise RetrievalError("Câu hỏi không được để trống.")

    if collection.count() == 0:
        raise RetrievalError(
            "Knowledge base đang rỗng. Hãy chạy setup_sample_data.py hoặc nạp dữ liệu trước."
        )

    detected_topic = topic or infer_topic(normalized_query)

    if settings.hybrid_search_enabled:
        from rag.hybrid import get_index, load_or_build, rrf_fuse
        index = get_index()
        if not index.is_ready():
            index = load_or_build()

        fetch_k = settings.hybrid_fetch_k
        vec_chunks = _vector_retrieve(normalized_query, top_k=fetch_k, topic=detected_topic)
        bm25_chunks = index.search(normalized_query, top_k=fetch_k, topic=detected_topic)

        # Nếu BM25 chưa sẵn (vd lần đầu chưa rebuild), dùng vector-only
        if not bm25_chunks and not vec_chunks:
            raise RetrievalError("Không tìm thấy context phù hợp trong knowledge base.")
        if not bm25_chunks:
            return vec_chunks[:top_k]
        if not vec_chunks:
            return bm25_chunks[:top_k]

        return rrf_fuse([vec_chunks, bm25_chunks], top_k=top_k)

    # Vector-only mode
    chunks = _vector_retrieve(normalized_query, top_k=top_k, topic=detected_topic)
    if not chunks:
        raise RetrievalError("Không tìm thấy context phù hợp trong knowledge base.")
    return chunks


def _build_chunks(
    documents: list[str],
    metadatas: list[dict[str, Any]],
    distances: list[float],
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for index, document in enumerate(documents):
        metadata = metadatas[index] if index < len(metadatas) else {}
        distance = distances[index] if index < len(distances) else None
        chunks.append(
            {
                "content": document,
                "metadata": metadata or {},
                "distance": distance,
                "score": round(1 / (1 + distance), 4) if distance is not None else None,
            }
        )
    return chunks


if __name__ == "__main__":
    # Test retrieval
    query = "Docker la gi?"
    results = retrieve(query)
    print(f"Found {len(results)} relevant chunks:")
    for item in results:
        print(item["metadata"].get("title", "Untitled"), "=>", item["content"][:100])
