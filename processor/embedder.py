import chromadb
from sentence_transformers import SentenceTransformer

# Model nhẹ, chạy local hoàn toàn, miễn phí
model = SentenceTransformer("all-MiniLM-L6-v2")

# Kết nối ChromaDB local
client = chromadb.PersistentClient(path="./db/chroma_store")
collection = client.get_or_create_collection("ai_knowledge")

def embed_and_store(chunks: list[dict]):
    """
    Embed các chunks và lưu vào ChromaDB
    
    Args:
        chunks: List các chunks với format {"id": str, "text": str, "metadata": dict}
    """
    texts = [c["text"] for c in chunks]
    ids = [c["id"] for c in chunks]
    metadatas = [c["metadata"] for c in chunks]

    # Embed toàn bộ (batch cho nhanh)
    embeddings = model.encode(texts).tolist()

    collection.add(
        embeddings=embeddings,
        documents=texts,
        metadatas=metadatas,
        ids=ids
    )
    print(f"Đã lưu {len(chunks)} chunks vào ChromaDB")

def clear_collection():
    """Xóa toàn bộ dữ liệu trong collection"""
    global collection
    client.delete_collection("ai_knowledge")
    collection = client.get_or_create_collection("ai_knowledge")
    print("Đã xóa toàn bộ dữ liệu trong collection")

if __name__ == "__main__":
    # Test embedding
    sample_chunks = [
        {
            "id": "test_1",
            "text": "Python is a programming language",
            "metadata": {"topic": "Python", "chunk_index": 0}
        }
    ]
    embed_and_store(sample_chunks)
    print("Embedding test completed")
