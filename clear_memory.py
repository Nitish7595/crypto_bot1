"""
Run this ONCE on Railway to clear phantom trades.
Upload this file, run it manually in Railway console, then delete it.

Railway console: click your service → Settings → Deploy → Console
Type: python clear_memory.py
"""
import json, os

files = ["agent_memory.json", "news_pattern_memory.json"]
for f in files:
    if os.path.exists(f):
        os.remove(f)
        print(f"Deleted {f}")
    else:
        print(f"{f} not found — already clean")

print("Memory cleared. Bot will start fresh with 0 trades.")
print("All future trades will only appear after Telegram confirms delivery.")
