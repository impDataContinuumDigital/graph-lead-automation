from scrapling.fetchers import Fetcher, FetcherSession

# with FetcherSession(impersonate='chrome') as session:  # Use latest version of Chrome's TLS fingerprint
#     page = session.get('https://www.google.com', stealthy_headers=True)
#     quotes = page.css('.quote .text::text').getall()

# print(quotes)

# Or use one-off requests
# page = Fetcher.get('https://kanoxconstruction.com/')
# quotes = page.css('.quote .text::text').getall()
# print(quotes)

page = Fetcher.get('https://www.google.com/')

print(page.css('h1::text').getall())
print(page.css('h2::text').getall())
