from fastapi import FastAPI
from pydantic import BaseModel
from rag.pipeline import chat

app = FastAPI()

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    answer: str

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    """
    Chat endpoint - nhận message và trả về answer
    """
    answer = chat(req.message)
    return ChatResponse(answer=answer)

@app.get("/")
async def root():
    return {"message": "AI Chatbot API is running"}

# Chạy: uvicorn api.main:app --reload --port 8000
