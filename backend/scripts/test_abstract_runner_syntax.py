import asyncio
import sys
import os

from dotenv import load_dotenv

# Add backend to path
sys.path.insert(0, os.path.abspath("backend"))

# Load env before imports
load_dotenv(os.path.join(os.path.abspath("backend"), ".env"))

async def test_imports():
    try:
        from services.abstract_runner import run_abstract_strategy_pipeline
        from services.scheduler import _run_strategy_job
        print("Imports successful. Syntax is valid.")
        return 0
    except Exception as e:
        print(f"Import failed: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(test_imports()))
