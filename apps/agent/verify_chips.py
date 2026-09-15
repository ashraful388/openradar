"""Spot checks for home + models page text."""
import re
import urllib.request

t = urllib.request.urlopen("http://127.0.0.1:3000/", timeout=30).read().decode("utf-8", errors="ignore")
links = re.findall(r'href="(/[^"]*)"', t)
print("links to /:", sum(1 for l in links if l in ("/", '/"')))

t = urllib.request.urlopen("http://127.0.0.1:3000/models", timeout=30).read().decode("utf-8", errors="ignore")
print("'Free models' on /models:", t.count("Free models"))
print("'search model id' on /models:", t.count("search model id"))
print("'all providers' on /models:", t.count("all providers"))
print("'chips-row' on /models:", t.count("chips-row"))

# Sample the chip filter row
i = t.find("search model id")
j = t.find("modality-pill", i)
print("--- snippet around the filters ---")
print(t[i:j+50][:1500])
