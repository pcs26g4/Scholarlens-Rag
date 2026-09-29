import os
import pytest
from dotenv import load_dotenv
import pandas as pd
from qdrant_client import QdrantClient
from ingestion.ingestion_csv import main as run_ingestion

load_dotenv()
COLLECTION_NAME = os.getenv('COLLECTION_NAME', 'student_validator_qa')
QDRANT_HOST = os.getenv('QDRANT_HOST', 'localhost')
QDRANT_PORT = int(os.getenv('QDRANT_PORT', 6333))

@pytest.fixture(scope="session")
def ensure_populated_qdrant():
    # Always (re)run ingestion to guarantee state
    run_ingestion()
    yield
    # Optionally: clear collection after

@pytest.fixture(scope="session")
def sample_qa_df():
    return pd.read_csv('qa.csv')

@pytest.fixture(scope="session")
def sample_rules_yaml():
    with open('business_rules.yaml', encoding='utf-8') as f:
        return f.read()