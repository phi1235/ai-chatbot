from __future__ import annotations

import chromadb
from sentence_transformers import SentenceTransformer

from config.settings import settings

model = SentenceTransformer(settings.embedding_model)
client = chromadb.PersistentClient(path=settings.chroma_path)
collection = client.get_or_create_collection(settings.chroma_collection)


def embed_and_store(chunks: list[dict]) -> None:
    """
    Embed các chunks chuẩn hóa và lưu vào ChromaDB.
    """
    if not chunks:
        print("Không có chunk nào để embed.")
        return

    texts = [c["content"] for c in chunks]
    ids = [c["chunk_id"] for c in chunks]
    metadatas = [
        {
            "doc_id": c["doc_id"],
            "title": c["title"],
            "section": c.get("section", ""),
            "topic": c.get("topic", "general"),
            "url": c.get("url", ""),
            "source": c.get("source", "website"),
            "updated_at": c.get("updated_at") or "",
            # session_id: "" cho global KB, "<id>" cho file user upload trong session.
            # Cho phép retriever filter chỉ chunks của session đó + global.
            "session_id": c.get("session_id", "") or "",
        }
        for c in chunks
    ]

    embeddings = model.encode(texts).tolist()
    existing = set(collection.get(ids=ids, include=[]).get("ids", []))
    new_payload = [
        (chunk_id, text, metadata, embedding)
        for chunk_id, text, metadata, embedding in zip(ids, texts, metadatas, embeddings)
        if chunk_id not in existing
    ]
    if not new_payload:
        print("Không có chunk mới để lưu vào ChromaDB.")
        return

    collection.add(
        ids=[item[0] for item in new_payload],
        documents=[item[1] for item in new_payload],
        metadatas=[item[2] for item in new_payload],
        embeddings=[item[3] for item in new_payload],
    )
    print(f"Đã lưu {len(new_payload)} chunks vào ChromaDB")
    _rebuild_bm25_if_enabled()


def clear_collection() -> None:
    global collection
    client.delete_collection(settings.chroma_collection)
    collection = client.get_or_create_collection(settings.chroma_collection)
    print("Đã xóa toàn bộ dữ liệu trong collection")
    _rebuild_bm25_if_enabled()


def delete_session_chunks(session_id: str) -> int:
    """Xoá tất cả chunks thuộc về 1 session (file upload). Trả về số chunks xoá."""
    if not session_id:
        return 0
    existing = collection.get(where={"session_id": session_id}, include=[])
    ids = existing.get("ids", []) or []
    if ids:
        collection.delete(ids=ids)
        _rebuild_bm25_if_enabled()
    return len(ids)


def _rebuild_bm25_if_enabled() -> None:
    """Rebuild BM25 index sau khi Chroma có thay đổi để 2 nguồn đồng bộ."""
    if not settings.hybrid_search_enabled:
        return
    try:
        from rag.hybrid import rebuild_from_chroma
        rebuild_from_chroma()
        print("Đã rebuild BM25 index")
    except Exception as exc:
        # Không fatal - hybrid search sẽ load_or_build lại khi query đầu tiên
        print(f"[WARN] Rebuild BM25 thất bại (sẽ rebuild khi query đầu): {exc}")


if __name__ == "__main__":
    sample_chunks = [
        {
            "chunk_id": "doc-001-chunk-01",
            "doc_id": "doc-001",
            "title": "Refund policy",
            "section": "Eligibility",
            "content": "Customers can request a refund within 30 days of purchase.",
            "topic": "policy",
            "url": "https://example.com/refund",
            "source": "website",
            "updated_at": "2026-04-22",
        }
    ]
    embed_and_store(sample_chunks)
    print("Embedding test completed")
