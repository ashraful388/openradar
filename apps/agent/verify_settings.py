"""Verify /settings renders with all the new sections."""
import urllib.request
t = urllib.request.urlopen("http://127.0.0.1:3000/settings", timeout=30).read().decode("utf-8", errors="ignore")
for n in ["Settings", "Agent", "Free detection", "Cheap flagships", "Data sources",
          "UI", "Notifications", "OpenRouter", "Hugging Face", "models.dev",
          "Run frequency", "Log level", "Max $/M output", "Respect b.ai pricing",
          "Save settings", "Reset to defaults", "Last snapshot", "Last refresh"]:
    print(f"  {n:30s}  {t.count(n)}")
