"""Start NEXA: python run.py  →  http://localhost:5050"""
import os

from nexa.app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5050)), debug=False, threaded=True)
