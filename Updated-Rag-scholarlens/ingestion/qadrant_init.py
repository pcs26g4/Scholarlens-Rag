import subprocess
import socket
import time
from qdrant_client import QdrantClient

def is_qdrant_running(host='localhost', port=6333):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.settimeout(1)
            s.connect((host, port))
            return True
        except Exception:
            return False

def start_qdrant_local(port=6333):
    import threading
    def _run():
        subprocess.run(['qdrant'], check=True)
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    # wait for qdrant to be available
    for _ in range(30):
        if is_qdrant_running('localhost', port):
            print("Qdrant is running.")
            return
        time.sleep(1)
    raise RuntimeError("Qdrant did not start in time.")

def ensure_qdrant():
    from dotenv import load_dotenv
    import os
    load_dotenv()
    host = os.getenv("QDRANT_HOST", "localhost")
    port = int(os.getenv("QDRANT_PORT", 6333))
    if is_qdrant_running(host, port):
        print(f"Qdrant found at {host}:{port}")
    else:
        print("Qdrant not found, starting local Qdrant...")
        start_qdrant_local(port)