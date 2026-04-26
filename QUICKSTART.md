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

## Bước 2: Cấu hình `.env` (2 phút)

1. Tạo API key tại https://openrouter.ai/
2. Copy template: `cp .env.example .env`
3. Mở `.env` và điền `OPENROUTER_API_KEY`. Các biến khác (port, log, model...) đã có sẵn default hợp lý.

```env
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=google/gemma-3-27b-it:free   # hoặc model free khác từ openrouter.ai
UVICORN_PORT=8000                              # backend port
STREAMLIT_SERVER_PORT=8501                     # UI port
```

> `uvicorn` và `streamlit` **tự đọc** `UVICORN_*`/`STREAMLIT_*` từ `.env` — không cần truyền flag.

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

### Cách A — chạy 2 terminal (dev nhanh)

Terminal 1 — Backend:
```bash
uvicorn api.main:app --reload
```

Terminal 2 — UI:
```bash
streamlit run ui/app.py
```

### Cách B — `run.sh` menu (tiện)

```bash
./run.sh
# Chọn 3 để chạy cả backend + UI
```

### Cách C — Docker (đóng gói)

```bash
docker compose up --build
# Lần đầu mất ~5 phút (build + load model HF)
```

## Bước 5: Test chatbot

Truy cập `http://localhost:${STREAMLIT_SERVER_PORT}` (mặc định 8501) và thử hỏi:
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
