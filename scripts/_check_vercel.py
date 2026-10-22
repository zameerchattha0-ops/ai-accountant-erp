import json
import urllib.request
from pathlib import Path

secret_file = Path("E:/Qoder/.secrets/vercel new.txt")
token = ""
for line in secret_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#"):
        token = line

headers = {"Authorization": f"Bearer {token}"}
url = "https://api.vercel.com/v13/deployments/dpl_J33yKACnBFr6Tu5BqAeZFJ6RhWa1"
req = urllib.request.Request(url, headers=headers)
try:
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())
        print("URL:", data.get("url"))
        print("Aliases:", data.get("alias"))
        print("Ready State:", data.get("readyState"))
except Exception as e:
    print("Error:", e)

