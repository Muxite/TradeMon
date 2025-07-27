from app.stocker import Stocker

if __name__ == "__main__":
    stocker = Stocker()
    stocker.run_worker()