# Quick Start Guide

## Bước 1: Setup môi trường (5 phút)

```bash
cd ai-chatbot

# Tạo virtual environment
python3 -m venv venv
source venv/bin/activate

# Cài đặt dependencies
pip install -r requirements.txt
```

## Bước 2: Cấu hình OpenRouter API (2 phút)

1. Tạo API key OpenRouter
2. Copy `.env.example` thành `.env`
3. Cập nhật file `.env`:

```env
OPENROUTER_API_KEY=sk-or-...your_actual_key_here
OPENROUTER_MODEL=openrouter/free
```

## Bước 3: Setup sample data (1 phút)

```bash
python setup_sample_data.py
```

Output:
```
 Đang xử lý sample data...
 Đã tạo 15 chunks
 Đã lưu vào ChromaDB
 Setup hoàn tất!
```

## Bước 4: Chạy ứng dụng (2 phút)

### Terminal 1 - Backend API:
```bash
uvicorn api.main:app --reload --port 8000
```

### Terminal 2 - Streamlit UI:
```bash
streamlit run ui/app.py
```

## Bước 5: Test chatbot

Truy cập http://localhost:8501 và thử hỏi:
- "Python là gì?"
- "Machine Learning có những loại nào?"
- "Web Development gồm những phần nào?"

## Thêm data của riêng bạn

Chỉnh sửa `setup_sample_data.py` và thêm documents:

```python
sample_docs = [
 {
 "topic": "Your Topic",
 "content": "Your content here..."
 }
]
```

Sau đó chạy lại:
```bash
python setup_sample_data.py
```

## Troubleshooting

### Lỗi "No module named 'chromadb'"
```bash
pip install -r requirements.txt
```

### Lỗi "OPENROUTER_API_KEY not found"
Kiểm tra file `.env` có đúng format và API key hợp lệ.

### Lỗi khi chạy API
Đảm bảo đã chạy `setup_sample_data.py` trước.

## Next Steps

1. Tùy chỉnh prompt trong `rag/generator.py`
2. Điều chỉnh chunk_size và overlap trong `processor/chunker.py`
3. Thay đổi số lượng context chunks bằng `RETRIEVAL_TOP_K`
4. Đọc `ARCHITECTURE.md` để hiểu gateway, orchestrator, guardrails, metrics
5. Deploy lên VPS

Chúc bạn thành công!
