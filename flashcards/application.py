"""Application composition and server startup."""

from http.server import ThreadingHTTPServer

from .config import HOST, PORT
from .database import init_db
from .web import Handler


def main() -> None:
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Flash Cards running at http://{HOST}:{PORT}")
    print("Create an account at /register, then log in to import and study decks.")
    server.serve_forever()
