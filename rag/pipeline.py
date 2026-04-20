from rag.retriever import retrieve
from rag.generator import generate_answer

def chat(query: str) -> str:
    """
    RAG pipeline: retrieve context và generate answer
    
    Args:
        query: Câu hỏi của user
    
    Returns:
        Câu trả lời
    """
    # Bước 1: tìm context liên quan
    relevant_chunks = retrieve(query, top_k=3)

    # Bước 2: generate câu trả lời
    answer = generate_answer(query, relevant_chunks)
    return answer

if __name__ == "__main__":
    # Test pipeline
    query = "What is Python?"
    answer = chat(query)
    print(f"Q: {query}")
    print(f"A: {answer}")
