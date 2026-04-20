def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """
    Chia text thành các đoạn nhỏ với overlap để không mất context
    
    Args:
        text: Text cần chia
        chunk_size: Kích thước mỗi chunk (mặc định 500 ký tự)
        overlap: Số ký tự overlap giữa các chunk (mặc định 50)
    
    Returns:
        List các chunks
    """
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start += chunk_size - overlap
    return chunks

def process_documents(docs: list[dict]) -> list[dict]:
    """
    Xử lý nhiều documents, chia thành chunks và thêm metadata
    
    Args:
        docs: List các document với format {"topic": str, "content": str}
    
    Returns:
        List các chunks với metadata
    """
    all_chunks = []
    for doc in docs:
        chunks = chunk_text(doc["content"])
        for i, chunk in enumerate(chunks):
            all_chunks.append({
                "id": f"{doc['topic']}_{i}",
                "text": chunk,
                "metadata": {"topic": doc["topic"], "chunk_index": i}
            })
    return all_chunks

if __name__ == "__main__":
    # Test chunking
    sample_doc = {
        "topic": "Python",
        "content": "Python is a high-level programming language. " * 50
    }
    chunks = process_documents([sample_doc])
    print(f"Created {len(chunks)} chunks from document")
    print(f"First chunk: {chunks[0]['text'][:100]}...")
