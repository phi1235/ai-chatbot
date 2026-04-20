#!/bin/bash

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}🤖 AI Chatbot Agent - Run Script${NC}"
echo ""

# Check if venv exists
if [ ! -d "venv" ]; then
    echo -e "${RED}❌ Virtual environment not found!${NC}"
    echo -e "${BLUE}Creating virtual environment...${NC}"
    python3 -m venv venv
    source venv/bin/activate
    echo -e "${BLUE}Installing dependencies...${NC}"
    pip install -r requirements.txt
    echo -e "${GREEN}✅ Setup complete!${NC}"
else
    source venv/bin/activate
fi

# Check if .env exists and has API key
if [ ! -f ".env" ]; then
    echo -e "${RED}❌ .env file not found!${NC}"
    echo "Please create .env file with your GEMINI_API_KEY"
    exit 1
fi

if ! grep -q "GEMINI_API_KEY=AIza" .env; then
    echo -e "${RED}⚠️  Warning: GEMINI_API_KEY might not be configured properly${NC}"
    echo "Please update .env file with your actual API key"
fi

# Check if ChromaDB has data
if [ ! -d "db/chroma_store" ] || [ -z "$(ls -A db/chroma_store)" ]; then
    echo -e "${BLUE}📦 No data found. Running setup_sample_data.py...${NC}"
    python setup_sample_data.py
    echo ""
fi

# Menu
echo -e "${GREEN}Choose an option:${NC}"
echo "1) Run Backend API (port 8000)"
echo "2) Run Streamlit UI (port 8501)"
echo "3) Run Both (in background)"
echo "4) Setup Sample Data"
echo "5) Test RAG Pipeline"
echo "6) Exit"
echo ""
read -p "Enter choice [1-6]: " choice

case $choice in
    1)
        echo -e "${BLUE}🚀 Starting FastAPI backend...${NC}"
        uvicorn api.main:app --reload --port 8000
        ;;
    2)
        echo -e "${BLUE}🚀 Starting Streamlit UI...${NC}"
        streamlit run ui/app.py
        ;;
    3)
        echo -e "${BLUE}🚀 Starting both services...${NC}"
        uvicorn api.main:app --reload --port 8000 &
        sleep 3
        streamlit run ui/app.py
        ;;
    4)
        echo -e "${BLUE}📦 Setting up sample data...${NC}"
        python setup_sample_data.py
        ;;
    5)
        echo -e "${BLUE}🧪 Testing RAG pipeline...${NC}"
        python rag/pipeline.py
        ;;
    6)
        echo -e "${GREEN}👋 Goodbye!${NC}"
        exit 0
        ;;
    *)
        echo -e "${RED}Invalid choice${NC}"
        exit 1
        ;;
esac
