"""
Script tạo sample data theo format document chuẩn để test pipeline local RAG.
"""
from processor.chunker import process_documents
from processor.embedder import clear_collection, embed_and_store

sample_docs = [
    {
        "id": "doc-python-001",
        "title": "Tổng quan Python",
        "url": "https://example.local/python-overview",
        "content": """
Tổng quan Python

Python là ngôn ngữ lập trình bậc cao, cú pháp rõ ràng và dễ đọc. Ngôn ngữ này được dùng rộng rãi trong tự động hóa, backend, khoa học dữ liệu và AI.

Ứng dụng chính

Python phù hợp cho scripting, web development, data analysis, machine learning và tích hợp hệ thống. Hệ sinh thái thư viện lớn là lý do Python thường được chọn để phát triển nhanh.

Ưu điểm

Python có cộng đồng lớn, tài liệu nhiều và tốc độ học nhanh. Điểm cần lưu ý là hiệu năng raw thường không bằng các ngôn ngữ biên dịch như C++ hoặc Rust.
""".strip(),
        "source": "sample",
        "updated_at": "2026-04-22",
        "topic": "engineering",
    },
    {
        "id": "doc-ml-001",
        "title": "Khái niệm Machine Learning",
        "url": "https://example.local/ml-basics",
        "content": """
Khái niệm Machine Learning

Machine Learning là nhánh của AI cho phép hệ thống học từ dữ liệu thay vì lập trình cứng toàn bộ luật xử lý.

Nhóm bài toán

Ba nhóm phổ biến là supervised learning, unsupervised learning và reinforcement learning. Mỗi nhóm phù hợp với kiểu dữ liệu và mục tiêu khác nhau.

Ứng dụng

Machine Learning được ứng dụng trong phân loại văn bản, gợi ý sản phẩm, phát hiện gian lận và dự báo nhu cầu.
""".strip(),
        "source": "sample",
        "updated_at": "2026-04-22",
        "topic": "ai",
    },
    {
        "id": "doc-policy-001",
        "title": "Chính sách hoàn tiền",
        "url": "https://example.local/refund-policy",
        "content": """
Chính sách hoàn tiền

Điều kiện áp dụng

Khách hàng được yêu cầu hoàn tiền trong vòng 30 ngày kể từ ngày thanh toán nếu dịch vụ chưa được sử dụng vượt quá giới hạn cho phép theo hợp đồng.

Hồ sơ cần có

Yêu cầu hoàn tiền cần kèm mã đơn hàng, thông tin liên hệ và lý do đề nghị hoàn tiền để bộ phận hỗ trợ đối chiếu.

Ngoại lệ

Các gói dùng thử miễn phí, dịch vụ đã kích hoạt không thể hoàn lại và các khoản phí tích hợp của bên thứ ba không thuộc phạm vi hoàn tiền.
""".strip(),
        "source": "sample",
        "updated_at": "2026-04-22",
        "topic": "policy",
    },
]


def setup_sample_data() -> None:
    print("Đang xử lý sample data...")
    clear_collection()
    chunks = process_documents(sample_docs)
    print(f"Đã tạo {len(chunks)} chunks")
    embed_and_store(chunks)
    print("Đã lưu sample data vào ChromaDB")
    print("Chạy API: uvicorn api.main:app --reload --port 8000")
    print("Chạy UI: streamlit run ui/app.py")


if __name__ == "__main__":
    setup_sample_data()
