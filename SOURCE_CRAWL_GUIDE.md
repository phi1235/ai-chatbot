# Huong Dan Start Source Va Crawl Data

File nay ghi lai cach khai bao source, crawl data, ingest vao knowledge base, va chay chatbot local.

## 1. Muc tieu

Pipeline cua repo nay dang di theo huong:

```text
source urls/files -> crawl -> clean -> chunk -> embed -> ChromaDB -> retrieve -> Ollama answer
```

Day la `RAG`, khong phai fine-tune.

- Du lieu duoc dua vao knowledge base
- Model local se doc context retrieve duoc de tra loi
- Khong can train lai model o buoc nay

## 2. Khai bao source o dau

Khai bao trong thu muc `sources/`.

Hien tai repo co san:

- `sources/policy.json`
- `sources/engineering.json`
- `sources/ai.json`
- `sources/docker.json`

Moi file dai dien cho 1 `topic`.

Vi du:

```json
[
 {
 "location": "https://example.com/refund-policy",
 "topic": "policy",
 "source": "website",
 "title": "Chinh sach hoan tien"
 },
 {
 "location": "docs/internal_refund.md",
 "topic": "policy",
 "source": "local_file",
 "title": "Huong dan hoan tien noi bo"
 }
]
```

## 3. Y nghia cac truong

- `location`: URL website hoac duong dan file local
- `topic`: nhan linh vuc, vi du `policy`, `banking`, `insurance`
- `source`: kieu nguon, vi du `website`, `local_file`
- `title`: ten tai lieu muon hien thi trong metadata

## 4. URL nao nen dung

Nen uu tien:

- docs chinh thuc
- FAQ
- knowledge base
- huong dan nghiep vu
- bai viet co cau truc ro
- file markdown/text noi bo

Khong nen uu tien:

- trang home co qua nhieu menu
- trang render JS nang
- trang khong lien quan truc tiep den linh vuc
- trang spam, tong hop, noi dung lap

## 5. Crawl co phai lam tay khong

Khong.

Anh khong can copy noi dung bang tay.
Anh chi can:

1. Khai bao danh sach source trong `sources/<topic>.json`
2. Chay lenh ingest

Script se tu:

1. doc source
2. crawl du lieu
3. clean
4. chunk
5. embed
6. luu vao ChromaDB

## 6. Lenh ingest

Nap du lieu theo topic:

```bash
source venv/bin/activate
python ingest.py --topic policy
```

Xoa knowledge base cu roi nap lai:

```bash
python ingest.py --topic policy --reset
```

Nap theo file source cu the:

```bash
python ingest.py --source-file sources/policy.json --reset
```

Neu khong truyen `--topic`, script se doc tat ca file trong `sources/`.

## 7. Du lieu se duoc luu o dau

- Raw data: `data/raw/`
- Clean data: `data/clean/`
- Vector DB: `db/chroma_store/`

## 8. Sau khi ingest thi chatbot tra loi the nao

Sau khi ingest xong:

1. user dat cau hoi
2. app retrieve chunk lien quan tu ChromaDB
3. Ollama doc context do
4. Ollama sinh cau tra loi

Nen nho:

- chatbot khong tu nho het data theo kieu train
- chatbot dang doc tri thuc da ingest vao luc tra loi

## 9. Chay chatbot local

### Buoc 1: Cai dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Buoc 2: Dam bao Ollama dang chay

Kiem tra:

```bash
curl http://127.0.0.1:11434/api/tags
```

Neu co JSON tra ve la duoc.

Tai model neu chua co:

```bash
ollama pull qwen2.5:7b-instruct
```

### Buoc 3: Ingest data

```bash
python ingest.py --topic policy --reset
```

### Buoc 4: Chay backend

```bash
uvicorn api.main:app --reload
```

### Buoc 5: Chay UI

Terminal khac:

```bash
source venv/bin/activate
streamlit run ui/app.py
```

## 9.1. Lenh start day du tu dau

Neu muon chay day du tu luc bat dau, dung dung thu tu nay.

### Terminal 1: chuan bi moi truong va ingest data

```bash
cd /home/nguyen-phi/ai-chatbot
source venv/bin/activate
curl http://127.0.0.1:11434/api/tags
python ingest.py --topic policy --reset
```

Neu `curl` tra ve JSON la Ollama dang chay.

Neu chua co model:

```bash
ollama pull qwen2.5:7b-instruct
```

### Terminal 2: start backend

```bash
cd /home/nguyen-phi/ai-chatbot
source venv/bin/activate
uvicorn api.main:app --reload
```

### Terminal 3: start frontend

```bash
cd /home/nguyen-phi/ai-chatbot
source venv/bin/activate
streamlit run ui/app.py
```

### URL de mo sau khi start

- Backend API: `http://localhost:8000`
- Frontend UI: `http://localhost:8501`

### Neu muon doi model Ollama truoc khi start backend

```bash
cd /home/nguyen-phi/ai-chatbot
source venv/bin/activate
export OLLAMA_MODEL="qwen2.5:7b-instruct"
uvicorn api.main:app --reload
```

### Lenh nhanh de nho

```bash
cd /home/nguyen-phi/ai-chatbot
source venv/bin/activate
python ingest.py --topic policy --reset
uvicorn api.main:app --reload
```

Terminal khac:

```bash
cd /home/nguyen-phi/ai-chatbot
source venv/bin/activate
streamlit run ui/app.py
```

## 10. Cach them linh vuc moi

Vi du muon them linh vuc `banking`:

1. Tao file `sources/banking.json`
2. Them danh sach URL/file lien quan
3. Chay:

```bash
python ingest.py --topic banking --reset
```

### Vi du san de test crawl URL that voi Docker docs

Repo da co san file:

- `sources/docker.json`

Chay:

```bash
cd /home/nguyen-phi/ai-chatbot
source venv/bin/activate
python ingest.py --topic docker --reset
```

Sau do chay backend va frontend nhu binh thuong de hoi chatbot ve Docker.

## 11. Cach cap nhat du lieu moi

Khi co tai lieu moi hoac URL moi:

1. sua file `sources/<topic>.json`
2. chay lai ingest

Neu muon lam moi toan bo KB cua topic:

```bash
python ingest.py --topic policy --reset
```

Neu muon cong don them:

```bash
python ingest.py --topic policy
```

## 12. Gioi han hien tai

Ban hien tai ho tro tot nhat cho:

- HTML don gian
- markdown
- text file local

Chua toi uu cho:

- PDF
- trang JS render nang
- website chong bot
- crawl tu dong lan theo link trong ca domain

## 13. Neu muon mo rong sau nay

Co the lam tiep:

1. parser PDF
2. crawl theo sitemap/domain whitelist
3. upsert theo hash de tranh index trung
4. scheduler crawl dinh ky
5. bot tra kem source da dung

## 14. Tom tat cach dung nhanh

1. Them source vao `sources/<topic>.json`
2. Chay `python ingest.py --topic <topic> --reset`
3. Chay `uvicorn api.main:app --reload`
4. Chay `streamlit run ui/app.py`
5. Chatbot se tra loi dua tren data da ingest
