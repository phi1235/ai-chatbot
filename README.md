# AI Chatbot Agent

> **Stack:** Python · ChromaDB · OpenRouter API · Streamlit · FastAPI
> **Môi trường:** Ubuntu (local laptop)

## Tổng quan

Chatbot AI sử dụng RAG (Retrieval-Augmented Generation) để trả lời câu hỏi dựa trên dữ liệu đã crawl, có API gateway, orchestrator, guardrails, citations, trace và metrics local.

```
[AI API] → crawl → chunking → embedding → ChromaDB
 ↓
[User] → Streamlit UI → API Gateway → Orchestrator → Guardrails → vector search → OpenRouter API → trả lời
```

## Lưu ý khi clone repo

Repo này **không kèm sẵn data** (`data/raw/`, `data/clean/`, `db/`) vì:
- Tránh vi phạm copyright của các nguồn được crawl (react.dev, kubernetes.io, postgres.org…)
- Tránh lộ lịch sử hội thoại cá nhân
- Giữ repo nhẹ

Sau khi clone, bạn cần tự `python ingest.py --reset` để crawl + index dữ liệu vào ChromaDB local của mình. Có thể chỉnh sửa `sources/*.json` để chọn nguồn riêng.

## Cài đặt

### 1. Tạo virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 2. Cài đặt dependencies

```bash
pip install -r requirements.txt
```

### 3. Cấu hình API key

Copy `.env.example` thành `.env` rồi cập nhật OpenRouter API key:

```env
OPENROUTER_API_KEY=your_actual_api_key_here
OPENROUTER_MODEL=openrouter/free
```

## Cấu trúc project

```
ai-chatbot/
├── .env # API keys
├── requirements.txt # Dependencies
├── crawler/
│ └── fetch_data.py # Crawl data từ AI API
├── processor/
│ ├── chunker.py # Chia nhỏ text
│ └── embedder.py # Embed và lưu ChromaDB
├── rag/
│ ├── retriever.py # Tìm kiếm vector
│ ├── generator.py # Gọi OpenRouter API
│ └── pipeline.py # RAG pipeline
├── api/
│ └── main.py # API gateway, health, metrics
├── orchestrator/ # Agent layer, memory, rate limit
├── guardrails/ # Input/output safety checks
├── observability/ # Local logging & metrics
├── ui/
│ └── app.py # Streamlit chat UI
└── db/
 └── chroma_store/ # ChromaDB local storage
```

## Sử dụng

### Bước 1: Crawl và xử lý data

```python
from crawler.fetch_data import crawl_topics
from processor.chunker import process_documents
from processor.embedder import embed_and_store

# Crawl data
topics = ["Python programming", "Machine Learning"]
docs = crawl_topics(topics)

# Chunk và embed
chunks = process_documents(docs)
embed_and_store(chunks)
```

### Bước 2: Chạy backend API

```bash
cd ai-chatbot
uvicorn api.main:app --reload --port 8000
```

### Bước 3: Chạy Streamlit UI

Mở terminal mới:

```bash
cd ai-chatbot
streamlit run ui/app.py
```

Truy cập: http://localhost:8501

## Test từng module

### Test chunking

```bash
python processor/chunker.py
```

### Test embedding

```bash
python processor/embedder.py
```

### Test retrieval

```bash
python rag/retriever.py
```

### Test generation

```bash
python rag/generator.py
```

### Test pipeline

```bash
python rag/pipeline.py
```

## Tối ưu

### Chunking

- **Chunk quá nhỏ (<200)**: Mất context → Tăng `chunk_size` lên 800
- **Chunk quá lớn (>1000)**: Chậm → Giảm `chunk_size` xuống 400
- **Overlap không đủ**: Câu trả lời bị cắt → Tăng `overlap` lên 100

### Prompt OpenRouter

Chỉnh sửa prompt trong `rag/generator.py` để cải thiện chất lượng câu trả lời.

## Lưu ý

- **OpenRouter**: Model và quota phụ thuộc cấu hình `OPENROUTER_MODEL`
- **ChromaDB**: Dữ liệu lưu local tại `./db/chroma_store/`
- **Sentence-transformers**: Lần đầu chạy sẽ download model (~90MB)

## Troubleshooting

### Lỗi "OPENROUTER_API_KEY not found"

Kiểm tra file `.env` và đảm bảo API key đúng.

### Lỗi "Collection not found"

Chạy lại bước embed data:

```python
from processor.embedder import embed_and_store
# ... embed lại data
```

### ChromaDB lỗi

Xóa folder `db/chroma_store/` và chạy lại từ đầu.

## License

MIT
