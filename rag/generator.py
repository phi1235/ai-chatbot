import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")  # free tier

def generate_answer(query: str, context_chunks: list[str]) -> str:
    """
    Generate câu trả lời dựa trên query và context
    
    Args:
        query: Câu hỏi của user
        context_chunks: List các đoạn text liên quan
    
    Returns:
        Câu trả lời được generate bởi Gemini
    """
    context = "\n\n".join(context_chunks)
    prompt = f"""Dựa vào thông tin sau đây để trả lời câu hỏi của người dùng.
Chỉ trả lời dựa trên thông tin được cung cấp. Nếu không có đủ thông tin, hãy nói thẳng.

=== THÔNG TIN ===
{context}

=== CÂU HỎI ===
{query}

=== TRẢ LỜI ==="""

    response = model.generate_content(prompt)
    return response.text

if __name__ == "__main__":
    # Test generation
    query = "What is Python?"
    context = ["Python is a high-level programming language."]
    answer = generate_answer(query, context)
    print(f"Answer: {answer}")
