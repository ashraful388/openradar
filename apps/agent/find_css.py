"""Find context around .providers-wrap."""
from pathlib import Path
t = Path("apps/web/styles/globals.css").read_text(encoding="utf-8")
i = t.find(".providers-wrap")
if i == -1:
    print("not found")
else:
    print(repr(t[max(0, i-100):i+30]))
