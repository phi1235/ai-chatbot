# AI Chatbot Agent

> **Stack:** Python · ChromaDB · Gemini API · Streamlit · FastAPI  
> **Môi trường:** Ubuntu (local laptop)

## Tổng quan

Chatbot AI sử dụng RAG (Retrieval-Augmented Generation) để trả lời câu hỏi dựa trên dữ liệu đã crawl.

```
[AI API] → crawl → chunking → embedding → ChromaDB
                                              ↓
[User] → Streamlit UI → FastAPI → vector search → Gemini API → trả lời
```

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

Lấy Gemini API key từ https://aistudio.google.com và cập nhật file `.env`:

```env
GEMINI_API_KEY=your_actual_api_key_here
```

## Cấu trúc project

```
ai-chatbot/
├── .env                    # API keys
├── requirements.txt        # Dependencies
├── crawler/
│   └── fetch_data.py      # Crawl data từ AI API
├── processor/
│   ├── chunker.py         # Chia nhỏ text
│   └── embedder.py        # Embed và lưu ChromaDB
├── rag/
│   ├── retriever.py       # Tìm kiếm vector
│   ├── generator.py       # Gọi Gemini API
│   └── pipeline.py        # RAG pipeline
├── api/
│   └── main.py            # FastAPI backend
├── ui/
│   └── app.py             # Streamlit chat UI
└── db/
    └── chroma_store/      # ChromaDB local storage
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

### Prompt Gemini

Chỉnh sửa prompt trong `rag/generator.py` để cải thiện chất lượng câu trả lời.

## Lưu ý

- **Gemini free tier**: 15 requests/phút, 1 triệu tokens/ngày
- **ChromaDB**: Dữ liệu lưu local tại `./db/chroma_store/`
- **Sentence-transformers**: Lần đầu chạy sẽ download model (~90MB)

## Troubleshooting

### Lỗi "GEMINI_API_KEY not found"

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
