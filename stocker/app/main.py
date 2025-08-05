from app.stocker import Stocker
import asyncio

if __name__ == "__main__":
    stocker = Stocker()
    asyncio.run(stocker.run_worker())