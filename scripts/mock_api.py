"""
A tiny local REST API that behaves like https://dummyjson.com/products.

Use it when you have no internet, or to demonstrate how APIs work.
It only uses Python's standard library, so nothing extra to install.

Run (from the project root):
    python scripts/mock_api.py              # serves on http://localhost:8000
    python scripts/mock_api.py --port 8001

Try it in a browser:
    http://localhost:8000/products?limit=5&skip=0
    http://localhost:8000/products/1

Point the pipeline at it by setting in .env:
    API_BASE_URL=http://localhost:8000              (pipeline on Windows)
    API_BASE_URL=http://host.docker.internal:8000   (pipeline inside Airflow/Docker)
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = PROJECT_ROOT / "data" / "reference" / "products_snapshot.json"


def load_products(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload["products"] if isinstance(payload, dict) else payload


def make_handler(products: list[dict]):
    class ProductHandler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: dict) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802 (name required by http.server)
            parsed = urlparse(self.path)
            parts = [part for part in parsed.path.split("/") if part]
            query = parse_qs(parsed.query)

            if parts == ["products"]:
                limit = int(query.get("limit", ["30"])[0])
                skip = int(query.get("skip", ["0"])[0])
                if limit == 0:
                    limit = len(products)
                page = products[skip: skip + limit]
                self._send(200, {"products": page, "total": len(products), "skip": skip, "limit": len(page)})
            elif len(parts) == 2 and parts[0] == "products" and parts[1].isdigit():
                match = next((p for p in products if int(p["id"]) == int(parts[1])), None)
                if match:
                    self._send(200, match)
                else:
                    self._send(404, {"message": f"Product with id '{parts[1]}' not found"})
            else:
                self._send(404, {"message": "Not found. Try /products"})

        def log_message(self, fmt, *args) -> None:
            sys.stderr.write("mock-api: " + fmt % args + "\n")

    return ProductHandler


def create_server(port: int = 8000, snapshot: Path = DEFAULT_SNAPSHOT, host: str = "0.0.0.0") -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(load_products(snapshot)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Local mock product API")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    args = parser.parse_args()
    server = create_server(args.port, args.snapshot)
    print(f"Mock API running on http://localhost:{args.port}/products  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()
