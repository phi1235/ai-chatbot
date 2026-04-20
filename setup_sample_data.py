"""
Script để tạo sample data và test toàn bộ pipeline
"""
from processor.chunker import process_documents
from processor.embedder import embed_and_store

# Sample data thay vì crawl từ API
sample_docs = [
    {
        "topic": "Python",
        "content": """Python là ngôn ngữ lập trình bậc cao, được thiết kế với triết lý 
        code dễ đọc và dễ viết. Python hỗ trợ nhiều paradigm lập trình như OOP, functional 
        programming, và procedural programming. Python được sử dụng rộng rãi trong web 
        development, data science, machine learning, automation, và nhiều lĩnh vực khác. 
        Python có cú pháp đơn giản, thư viện phong phú, và cộng đồng developer lớn."""
    },
    {
        "topic": "Machine Learning",
        "content": """Machine Learning là một nhánh của AI, cho phép máy tính học từ dữ liệu 
        mà không cần lập trình cụ thể. Có 3 loại chính: supervised learning (học có giám sát), 
        unsupervised learning (học không giám sát), và reinforcement learning (học tăng cường). 
        Machine Learning được ứng dụng trong nhận dạng hình ảnh, xử lý ngôn ngữ tự nhiên, 
        recommendation systems, và nhiều lĩnh vực khác. Các thuật toán phổ biến bao gồm 
        linear regression, decision trees, neural networks, và SVM."""
    },
    {
        "topic": "Web Development",
        "content": """Web Development là quá trình xây dựng website và web application. 
        Gồm 2 phần chính: Frontend (giao diện người dùng) sử dụng HTML, CSS, JavaScript, 
        và Backend (server-side) sử dụng Python, Node.js, Java, PHP. Modern web development 
        sử dụng frameworks như React, Vue, Angular cho frontend và Django, Flask, Express 
        cho backend. RESTful API và GraphQL là các cách phổ biến để frontend và backend 
        giao tiếp với nhau."""
    }
]

def setup_sample_data():
    """Tạo sample data và lưu vào ChromaDB"""
    print("🔄 Đang xử lý sample data...")
    
    # Chunk documents
    chunks = process_documents(sample_docs)
    print(f"✅ Đã tạo {len(chunks)} chunks")
    
    # Embed và lưu vào ChromaDB
    embed_and_store(chunks)
    print("✅ Đã lưu vào ChromaDB")
    print("\n🎉 Setup hoàn tất! Bây giờ bạn có thể:")
    print("   1. Chạy API: uvicorn api.main:app --reload --port 8000")
    print("   2. Chạy UI: streamlit run ui/app.py")

if __name__ == "__main__":
    setup_sample_data()
