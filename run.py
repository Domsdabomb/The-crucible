"""
Development entry point.

    python run.py

For production use a WSGI server:
    gunicorn "app:create_app()" --bind 0.0.0.0:8000
"""

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
