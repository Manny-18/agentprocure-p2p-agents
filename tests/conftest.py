"""Tests always run offline, whatever .env says: they stay fast and repeatable and never spend API quota.

Set here, before any test imports agentprocure; python-dotenv does not override variables that already exist.
"""
import os

os.environ["LLM_PROVIDER"] = "offline"
os.environ["RAG_EMBEDDINGS"] = ""
