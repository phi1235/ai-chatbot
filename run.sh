#!/bin/bash
set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

# Load .env (single source of truth)
if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
else
    echo -e "${RED}.env không tồn tại. Copy .env.example thành .env trước khi chạy.${NC}"
    exit 1
fi

echo -e "${BLUE}AI Chatbot Agent - Run Script${NC}"
echo -e "${BLUE}backend=${UVICORN_HOST}:${UVICORN_PORT}  ui=${STREAMLIT_SERVER_ADDRESS}:${STREAMLIT_SERVER_PORT}${NC}"
echo ""

# venv setup
if [ ! -d "venv" ]; then
    echo -e "${RED}Virtual environment not found.${NC}"
    echo -e "${BLUE}Creating virtual environment...${NC}"
    python3 -m venv venv
    # shellcheck disable=SC1091
    source venv/bin/activate
    echo -e "${BLUE}Installing dependencies...${NC}"
    pip install -r requirements.txt
    echo -e "${GREEN}Setup complete.${NC}"
else
    # shellcheck disable=SC1091
    source venv/bin/activate
fi

# Auto-ingest nếu collection rỗng
COLLECTION_COUNT=$(python -c "
import os, chromadb
c = chromadb.PersistentClient(path=os.environ['CHROMA_PATH'])
col = c.get_or_create_collection(os.environ['CHROMA_COLLECTION'])
print(col.count())
")

if [ "${COLLECTION_COUNT}" -eq 0 ]; then
    echo -e "${BLUE}Collection rỗng. Chạy setup_sample_data.py...${NC}"
    python setup_sample_data.py
    echo ""
fi

# Menu
echo -e "${GREEN}Choose an option:${NC}"
echo "1) Run Backend API   (${UVICORN_HOST}:${UVICORN_PORT})"
echo "2) Run Streamlit UI  (${STREAMLIT_SERVER_ADDRESS}:${STREAMLIT_SERVER_PORT})"
echo "3) Run Both (backend in background)"
echo "4) Setup Sample Data"
echo "5) Test RAG Pipeline"
echo "6) Exit"
echo ""
read -rp "Enter choice [1-6]: " choice

# uvicorn / streamlit tự đọc UVICORN_*/STREAMLIT_* từ env, không cần flag
case $choice in
    1)
        echo -e "${BLUE}Starting FastAPI backend...${NC}"
        uvicorn api.main:app --reload
        ;;
    2)
        echo -e "${BLUE}Starting Streamlit UI...${NC}"
        streamlit run ui/app.py
        ;;
    3)
        echo -e "${BLUE}Starting both services...${NC}"
        uvicorn api.main:app --reload &
        BACKEND_PID=$!
        trap 'kill $BACKEND_PID 2>/dev/null || true' EXIT
        sleep 3
        streamlit run ui/app.py
        ;;
    4)
        echo -e "${BLUE}Setting up sample data...${NC}"
        python setup_sample_data.py
        ;;
    5)
        echo -e "${BLUE}Testing RAG pipeline...${NC}"
        python rag/pipeline.py
        ;;
    6)
        echo -e "${GREEN}Goodbye!${NC}"
        exit 0
        ;;
    *)
        echo -e "${RED}Invalid choice${NC}"
        exit 1
        ;;
esac
