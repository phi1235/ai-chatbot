import httpx
import json

AI_API_URL = "https://api-cua-ai-khac.com/v1/..."
HEADERS = {"Authorization": "Bearer YOUR_TOKEN"}

def fetch_data(topic: str) -> str:
    """Fetch data from AI API for a given topic"""
    try:
        response = httpx.post(AI_API_URL, headers=HEADERS, json={
            "prompt": topic,
            "max_tokens": 1000
        })
        data = response.json()
        return data["choices"][0]["text"]
    except Exception as e:
        print(f"Error fetching data: {e}")
        return ""

def crawl_topics(topics: list[str]) -> list[dict]:
    """Crawl multiple topics and return results"""
    results = []
    for topic in topics:
        text = fetch_data(topic)
        if text:
            results.append({"topic": topic, "content": text})
    return results

if __name__ == "__main__":
    # Example usage
    topics = ["Python programming", "Machine Learning", "Web Development"]
    results = crawl_topics(topics)
    print(f"Crawled {len(results)} topics")
