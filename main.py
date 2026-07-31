import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.main import app


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
