import asyncio
import logging
import sys
import os

# Ensure backend root is in pythonpath
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.hmm_retrain import retrain_all_hmm_models

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", stream=sys.stdout)

if __name__ == "__main__":
    asyncio.run(retrain_all_hmm_models())
