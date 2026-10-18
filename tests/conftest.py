import os, sys
os.environ.update(DATA_MODE="synthetic", SQLITE_PATH=":memory:"); os.environ.pop("SUPABASE_JWT_SECRET", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
