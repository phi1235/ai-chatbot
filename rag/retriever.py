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


def retrieve(query: str, top_k: int = 3, topic: str | None = None) -> list[dict[str, Any]]:
    """
    Tìm các chunk liên quan nhất và trả cả metadata để generator trích dẫn được nguồn.

    Chiến lược: nếu detect được topic thì query Chroma với filter topic trước (đảm bảo
    đúng chủ đề kể cả khi embedding similarity yếu cho query tiếng Việt). Nếu không có
    kết quả mới fallback sang query không filter.
    """
    normalized_query = query.strip()
    if not normalized_query:
        raise RetrievalError("Câu hỏi không được để trống.")

    if collection.count() == 0:
        raise RetrievalError(
            "Knowledge base đang rỗng. Hãy chạy setup_sample_data.py hoặc nạp dữ liệu trước."
        )

    detected_topic = topic or infer_topic(normalized_query)

    # Ưu tiên 1: query với topic filter
    if detected_topic:
        results = _query_collection(normalized_query, top_k=top_k, topic=detected_topic)
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        if documents:
            return _build_chunks(documents, metadatas, distances)

    # Ưu tiên 2: không filter (fallback)
    results = _query_collection(normalized_query, top_k=top_k, topic=None)
    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]
    if not documents:
        raise RetrievalError("Không tìm thấy context phù hợp trong knowledge base.")
    return _build_chunks(documents, metadatas, distances)


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
