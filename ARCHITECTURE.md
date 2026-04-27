# Production-style RAG Chatbot Architecture

Repo này được nâng cấp theo hướng gần với kiến trúc AI chatbot trong ảnh tham khảo, nhưng vẫn giữ tiêu chí local-first để dễ học, dễ chạy và dễ mở rộng.

## Luồng online

```text
Clients
 -> Streamlit UI
 -> FastAPI API Gateway
 -> Agent Orchestrator
 -> Guardrails
 -> RAG Pipeline
 -> ChromaDB Retriever
 -> OpenRouter LLM Generator
 -> Response Layer
```

## Thành phần chính

| Lớp | File/thư mục | Vai trò |
|---|---|---|
| Clients | `ui/app.py` | Giao diện chat, gửi `session_id`, hiển thị citation và trace |
| API Gateway | `api/main.py` | Auth API key tùy chọn, rate limit, validation, health, metrics |
| Orchestrator | `orchestrator/agent.py` | Điều phối request, session memory, guardrails, RAG, metrics |
| Guardrails | `guardrails/safety.py` | Chặn prompt injection/toxic input, redact email/phone |
| Core config | `config/settings.py` | Cấu hình tập trung qua `.env` |
| Observability | `observability/` | Logger và metrics in-memory local |
| RAG Pipeline | `rag/` | Detect topic, retrieve context, build citation, gọi LLM |
| Vector DB | `processor/embedder.py`, `rag/retriever.py` | Embed và search trong ChromaDB |
| Data ingestion | `ingest.py`, `crawler/`, `processor/` | Crawl/read source, clean, chunk, embed, index |

## API endpoints

- `GET /`: trạng thái tổng quan.
- `GET /health`: health check đơn giản.
- `GET /metrics`: snapshot metrics local.
- `POST /chat`: hỏi đáp RAG production-style.

Ví dụ request:

```json
{
 "message": "Python là gì?",
 "session_id": "local-session-1",
 "user_id": "demo-user"
}
```

Ví dụ response:

```json
{
 "answer": "...",
 "citations": [
 {
 "title": "Tổng quan Python",
 "url": "https://example.local/python-overview",
 "section": "Tổng quan Python",
 "source": "sample",
 "score": 0.82
 }
 ],
 "trace": {
 "request_id": "...",
 "session_id": "local-session-1",
 "detected_topic": "engineering",
 "retrieval_count": 4,
 "latency_ms": 1234.56,
 "safety_flags": []
 }
}
```

## Những phần đã có so với ảnh

- API gateway cơ bản: API key tùy chọn, rate limit, validation qua Pydantic.
- Agent layer: orchestrator, session memory in-memory, router topic, prompt builder nằm trong generator.
- Guardrails: input/output rules, PII redaction, prompt injection blocking.
- RAG pipeline: retrieval, metadata citation, context builder, ChromaDB vector storage.
- Observability: local metrics, structured-ish logging, trace trả về client.
- Data ingestion: crawl/read URL hoặc file, clean, chunk, embed, index.

## Những phần nên nâng cấp tiếp khi đi production thật

- Thay in-memory rate limit/session memory bằng Redis.
- Thêm re-ranker cross-encoder trước context builder.
- Thêm Elasticsearch/BM25 để hybrid search.
- Thêm OpenTelemetry, Prometheus, Grafana, Loki/ELK.
- Thêm auth OAuth2/JWT, WAF/reverse proxy, request signing.
- Thêm offline evaluation dataset, precision/recall/faithfulness checks.
- Thêm Docker Compose, CI, test suite, blue/green deploy.
