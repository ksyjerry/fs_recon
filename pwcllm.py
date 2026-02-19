import requests
import json

url = "https://genai-sharedservice-americas.pwcinternal.com/chat/completions"
headers = {
    "Content-Type": "application/json",
    "api-key": "sk-k7ZAoJmlclL75pjwHgEcFw"
}

data = {
    "model": "bedrock.anthropic.claude-opus-4-6",
    "messages": [
        {
            "role": "user",
            "content": "대한민국의 수도는?"
        }
    ]
}

response = requests.post(url, headers=headers, data=json.dumps(data))
result = response.json()

print(result["choices"][0]["message"]["content"])
