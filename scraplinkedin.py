from scrapling import Fetcher
from urllib.parse import quote

query = "www.linkedin.com/KanoxConstruction"

url = f"https://www.bing.com/search?q={quote(query)}"

page = Fetcher.get(url)

print("Status:", page.status)

results = page.css("li.b_algo")

print("Results Found:", len(results))

for i, result in enumerate(results[:5]):
    print(f"\n--- Result {i+1} ---")
    print(result.get()[:1000])