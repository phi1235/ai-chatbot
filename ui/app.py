import streamlit as st
import httpx

st.title("🤖 AI Chatbot")

if "messages" not in st.session_state:
    st.session_state.messages = []

# Hiển thị lịch sử chat
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# Input từ user
if prompt := st.chat_input("Hỏi gì đi..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    # Gọi API
    with st.chat_message("assistant"):
        with st.spinner("Đang suy nghĩ..."):
            try:
                response = httpx.post(
                    "http://localhost:8000/chat",
                    json={"message": prompt},
                    timeout=30.0
                )
                answer = response.json()["answer"]
                st.write(answer)
                st.session_state.messages.append({"role": "assistant", "content": answer})
            except Exception as e:
                st.error(f"Lỗi: {e}")

# Chạy: streamlit run ui/app.py
