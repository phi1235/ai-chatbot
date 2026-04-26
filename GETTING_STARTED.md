# Getting Started - AI Chatbot Agent

## Tổng quan

Bạn vừa nhận được một project AI Chatbot production-style local với:
- RAG (Retrieval-Augmented Generation) pipeline
- ChromaDB vector database
- OpenRouter API integration
- FastAPI API Gateway
- Agent orchestrator, rate limit, guardrails, citations, trace
- Streamlit chat UI
- Sample data sẵn sàng để test

## Cách chạy nhanh nhất (3 bước)

### Bước 1: Cài đặt dependencies

```bash
cd ai-chatbot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Bước 2: Cấu hình OpenRouter API key

Mở file `.env` và thay thế:
```env
OPENROUTER_API_KEY=your_api_key_here
OPENROUTER_MODEL=openrouter/free
```

Bạn có thể copy từ `.env.example` rồi điền key thật.

### Bước 3: Chạy ứng dụng

**Cách 1: Sử dụng run script (Khuyến nghị)**
```bash
./run.sh
```
Chọn option 3 để chạy cả backend và UI.

**Cách 2: Chạy thủ công**
```bash
# Terminal 1 - Backend
uvicorn api.main:app --reload --port 8000

# Terminal 2 - UI
streamlit run ui/app.py
```

Truy cập: http://localhost:8501

## Cấu trúc project

```
ai-chatbot/
│
├── README.md # Documentation đầy đủ
├── QUICKSTART.md # Hướng dẫn nhanh
├── PROJECT_SUMMARY.md # Tổng kết project
├── GETTING_STARTED.md # File này
│
├── requirements.txt # Dependencies
├── .env # API keys
├── .gitignore # Git ignore
├── run.sh # Run script tiện lợi
├── setup_sample_data.py # Setup data mẫu
│
├── crawler/ # Module crawl data
│ ├── __init__.py
│ └── fetch_data.py # Crawl từ AI API
│
├── processor/ # Module xử lý data
│ ├── __init__.py
│ ├── chunker.py # Chia text thành chunks
│ └── embedder.py # Embed và lưu ChromaDB
│
├── rag/ # RAG pipeline
│ ├── __init__.py
│ ├── retriever.py # Vector search
│ ├── generator.py # OpenRouter API
│ └── pipeline.py # RAG pipeline
│
├── api/ # FastAPI backend
│ ├── __init__.py
│ └── main.py # API gateway, health, metrics
│
├── orchestrator/ # Agent layer
│ ├── agent.py # Điều phối request
│ ├── memory.py # Session memory local
│ └── rate_limiter.py # Rate limit local
│
├── guardrails/ # Safety layer
│ └── safety.py # Input/output guardrails
│
├── observability/ # Logging & metrics
│ ├── logger.py
│ └── metrics.py
│
├── ui/ # Streamlit UI
│ ├── __init__.py
│ └── app.py # Chat interface
│
└── db/ # Database
 └── chroma_store/ # ChromaDB storage
```

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

### Test full pipeline
```bash
python rag/pipeline.py
```

## Câu hỏi mẫu để test

Sau khi chạy `setup_sample_data.py`, bạn có thể hỏi:

1. **Về Python:**
 - "Python là gì?"
 - "Python được dùng để làm gì?"
 - "Python có những ưu điểm gì?"

2. **Về Machine Learning:**
 - "Machine Learning là gì?"
 - "Có những loại Machine Learning nào?"
 - "Machine Learning được ứng dụng ở đâu?"

3. **Về Web Development:**
 - "Web Development gồm những phần nào?"
 - "Frontend và Backend khác nhau như thế nào?"
 - "Những framework phổ biến trong web development?"

## Tùy chỉnh

### Thêm data của riêng bạn

Chỉnh sửa `setup_sample_data.py`:

```python
sample_docs = [
 {
 "topic": "Your Topic",
 "content": "Your detailed content here..."
 },
 # Thêm nhiều documents...
]
```

Chạy lại:
```bash
python setup_sample_data.py
```

### Thay đổi chunk size

File: `processor/chunker.py`
```python
def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50):
 # Điều chỉnh chunk_size và overlap
```

### Thay đổi số lượng context

File: `rag/pipeline.py`
```python
relevant_chunks = retrieve(query, top_k=3) # Tăng/giảm top_k
```

### Tùy chỉnh prompt

File: `rag/generator.py` - Chỉnh sửa prompt template để thay đổi cách AI trả lời.

## Troubleshooting

### Lỗi: "No module named 'chromadb'"
```bash
source venv/bin/activate
pip install -r requirements.txt
```

### Lỗi: "OPENROUTER_API_KEY not found"
Kiểm tra file `.env` có đúng format:
```env
OPENROUTER_API_KEY=sk-or-...
```

### Lỗi: "Collection 'ai_knowledge' not found"
Chạy setup data:
```bash
python setup_sample_data.py
```

### Backend không chạy được
Kiểm tra port 8000 có bị chiếm không:
```bash
lsof -i :8000
```

### UI không kết nối được backend
Đảm bảo backend đang chạy ở port 8000:
```bash
curl http://localhost:8000/
```

## Đọc thêm

- **README.md**: Documentation đầy đủ về architecture và features
- **QUICKSTART.md**: Hướng dẫn quick start chi tiết
- **PROJECT_SUMMARY.md**: Tổng kết project và tech stack

## Học thêm

### RAG (Retrieval-Augmented Generation)
- Kết hợp retrieval (tìm kiếm) và generation (sinh text)
- Giúp AI trả lời dựa trên knowledge base cụ thể
- Giảm hallucination (bịa đặt thông tin)

### ChromaDB
- Vector database chạy local
- Lưu embeddings và metadata
- Hỗ trợ similarity search

### Sentence Transformers
- Model embedding text thành vectors
- Model "all-MiniLM-L6-v2" nhẹ (~90MB)
- Chạy hoàn toàn local, không cần API

### OpenRouter API
- Gateway gọi nhiều model LLM qua OpenAI-compatible API
- Repo đọc cấu hình từ `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `OPENROUTER_MODEL`

## Next Steps

1. Chạy thử với sample data
2. Thêm data của riêng bạn
3. Tùy chỉnh prompt và parameters
4. Thêm features:
 - File upload (PDF, DOCX)
 - Chat history với SQLite hoặc Redis
 - Authentication OAuth2/JWT
 - Export conversations
5. Đọc thêm `ARCHITECTURE.md` và deploy lên VPS

## Support

Nếu gặp vấn đề:
1. Kiểm tra Troubleshooting section
2. Đọc README.md để hiểu rõ hơn
3. Test từng module riêng lẻ
4. Kiểm tra logs trong terminal

## Chúc mừng!

Bạn đã có một AI Chatbot hoàn chỉnh! Hãy bắt đầu khám phá và tùy chỉnh theo nhu cầu của bạn.

Happy coding!
