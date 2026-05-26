"""测试 Qwen API 连通性"""
import http.client
import json
import ssl
from config import config

api_key = config.QWEN_API_KEY
ctx = ssl._create_unverified_context()
conn = http.client.HTTPSConnection("dashscope.aliyuncs.com", context=ctx)

payload = json.dumps({
    "model": "qwen-plus",
    "input": {"messages": [{"role": "user", "content": "Say hi in one word"}]},
    "parameters": {"result_format": "message", "temperature": 0.7}
})
headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
}

conn.request("POST", "/api/v1/services/aigc/text-generation/generation", payload, headers)
resp = conn.getresponse()
data = json.loads(resp.read().decode())
print(f"HTTP {resp.status}")
print(f"Response: {data['output']['choices'][0]['message']['content']}")
conn.close()
