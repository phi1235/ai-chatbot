import chromadb
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("all-MiniLM-L6-v2")
client = chromadb.PersistentClient(path="./db/chroma_store")
collection = client.get_collection("ai_knowledge")

def retrieve(query: str, top_k: int = 3) -> list[str]:
    """
    Tìm kiếm các đoạn text liên quan nhất đến query
    
    Args:
        query: Câu hỏi của user
        top_k: Số lượng kết quả trả về (mặc định 3)
    
    Returns:
        List các đoạn text liên quan nhất
    """
    query_embedding = model.encode([query]).tolist()
    results = collection.query(
        query_embeddings=query_embedding,
        n_results=top_k
    )
    return results["documents"][0]  # list các đoạn text liên quan nhất

if __name__ == "__main__":
    # Test retrieval
    query = "What is Python?"
    results = retrieve(query)
    print(f"Found {len(results)} relevant chunks:")
    for i, result in enumerate(results, 1):
        print(f"{i}. {result[:100]}...")
