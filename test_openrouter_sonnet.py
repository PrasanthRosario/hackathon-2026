import os, requests, dotenv
dotenv.load_dotenv(os.path.join(os.path.dirname(__file__), "backend", ".env"))
key = os.environ.get("OPENROUTER_API_KEY", "")
url = "https://openrouter.ai/api/v1/chat/completions"
res = requests.post(url, headers={"Authorization": f"Bearer {key}"}, json={"model": "anthropic/claude-sonnet-4-6", "messages": [{"role": "user", "content": "Hello from Offset test!"}]})
print("STATUS:", res.status_code)
print("RESPONSE:", res.json().get("choices", [{}])[0].get("message", {}).get("content") or res.json())
