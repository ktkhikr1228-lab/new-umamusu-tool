"""確認画面のWebサーバ。Python標準ライブラリのhttp.serverだけで動かす。

Tailscale内での利用を前提にしている(ログインなし)。
外部サイトからの書き換えを防ぐため、書き込みAPIは独自ヘッダと同一オリジンを必須にする。
"""
from __future__ import annotations

import json
import mimetypes
import sqlite3
import threading
import time
import traceback
from contextlib import contextmanager
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import db, review
from .config import Config
from .importer import import_all
from .skill_master import SkillMaster

STATIC_DIR = Path(__file__).resolve().parent / "static"
WRITE_HEADER = "X-Guide-App"
MAX_BODY = 256 * 1024


class App:
    """サーバ全体で共有する状態。DB接続はリクエストごとに開く(スレッドごとに別接続が必要なため)。"""

    def __init__(self, config: Config):
        self.config = config
        self.master = SkillMaster.load(config.skill_master_path)
        self.images = review.ImageIndex(config.screenshots_dir)
        self.import_lock = threading.Lock()
        self.last_import: dict | None = None
        db.connect(config.db_path).close()  # 起動時にテーブルを用意

    @contextmanager
    def connect(self):
        conn: sqlite3.Connection = db.connect(self.config.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def run_import(self) -> dict:
        with self.import_lock, self.connect() as conn:
            report = import_all(conn, self.config.extracted_dir, self.master)
        self.last_import = {
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "files": len(report.files),
            "added": report.added,
            "unchanged": report.unchanged,
            "problems": report.problems[:50],
        }
        return self.last_import


class Handler(BaseHTTPRequestHandler):
    app: App  # make_server で差し込む
    server_version = "guide_app/1"

    # ---- 共通 ----
    def log_message(self, fmt, *args):  # アクセスログは静かにする(エラーは別に出る)
        pass

    def send_json(self, data, status=HTTPStatus.OK):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, message, status=HTTPStatus.BAD_REQUEST):
        self.send_json({"error": message}, status)

    def send_file(self, path: Path, cache: str = "no-cache"):
        data = path.read_bytes()
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", cache)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise review.ReviewError("送信データが大きすぎます")
        data = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(data, dict):
            raise review.ReviewError("送信データの形式が不正です")
        return data

    def write_allowed(self) -> bool:
        if self.headers.get(WRITE_HEADER) != "1":
            return False
        origin = self.headers.get("Origin")
        return origin is None or urlparse(origin).netloc == self.headers.get("Host")

    # ---- ルーティング ----
    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def dispatch(self, method: str):
        url = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if method == "POST" and not self.write_allowed():
                return self.send_error_json("この操作は確認画面からのみ行えます", HTTPStatus.FORBIDDEN)
            route = ROUTES.get((method, url.path))
            if route is None and method == "POST" and url.path.startswith("/api/rows/"):
                return self.post_row(url.path.rsplit("/", 1)[-1])
            if route is None:
                if method == "GET":
                    return self.static(url.path)
                return self.send_error_json("見つかりません", HTTPStatus.NOT_FOUND)
            return route(self, query)
        except review.ReviewError as error:
            self.send_error_json(str(error))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            self.send_error_json(f"リクエストが不正です: {error}")
        except Exception:  # noqa: BLE001 - 画面に500を返し、詳細はログへ
            traceback.print_exc()
            self.send_error_json("サーバでエラーが起きました(ログを確認してください)", HTTPStatus.INTERNAL_SERVER_ERROR)

    def static(self, path: str):
        if path in ("", "/"):
            path = "/index.html"
        target = (STATIC_DIR / path.lstrip("/")).resolve()
        if STATIC_DIR not in target.parents or not target.is_file():
            return self.send_error_json("見つかりません", HTTPStatus.NOT_FOUND)
        self.send_file(target)

    # ---- API ----
    def get_overview(self, query):
        with self.app.connect() as conn:
            events = review.overview(conn)
        self.send_json({"events": events, "last_import": self.app.last_import})

    def get_group(self, query):
        with self.app.connect() as conn:
            data = review.group(conn, self.app.master, query["event"], query["race"], query["strategy"])
        for image in data["images"]:
            image["found"] = self.app.images.find(data["event"], image["file"]) is not None
        self.send_json(data)

    def get_master(self, query):
        self.send_file_json_cached(self.app.master.names)

    def send_file_json_cached(self, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "max-age=300")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def get_image(self, query):
        path = self.app.images.find(query["event"], query["file"])
        if path is None:
            return self.send_error_json("画像が見つかりません", HTTPStatus.NOT_FOUND)
        self.send_file(path, cache="max-age=86400")

    def post_row(self, row_id: str):
        with self.app.connect() as conn:
            row = review.update_row(conn, int(row_id), self.read_json())
        self.send_json(row)

    def post_review_image(self, query):
        body = self.read_json()
        with self.app.connect() as conn:
            result = review.review_image(conn, self.app.master, body["event"], body["file"],
                                         body["race"], body["strategy"])
        self.send_json(result)

    def post_images_tier(self, query):
        body = self.read_json()
        with self.app.connect() as conn:
            result = review.set_images_tier(conn, body["event"], body["race"], body["strategy"],
                                            list(body["files"]), body["tier"])
        self.send_json(result)

    def post_import(self, query):
        self.send_json(self.app.run_import())


ROUTES = {
    ("GET", "/api/overview"): Handler.get_overview,
    ("GET", "/api/group"): Handler.get_group,
    ("GET", "/api/master"): Handler.get_master,
    ("GET", "/api/image"): Handler.get_image,
    ("POST", "/api/review-image"): Handler.post_review_image,
    ("POST", "/api/images-tier"): Handler.post_images_tier,
    ("POST", "/api/import"): Handler.post_import,
}


def start_auto_import(app: App, interval: int) -> threading.Thread | None:
    """新しい抽出CSVを定期的に取り込む。"""
    if interval <= 0:
        return None

    def loop():
        while True:
            try:
                app.run_import()
            except Exception:  # noqa: BLE001 - 取り込み失敗でサーバは止めない
                traceback.print_exc()
            time.sleep(interval)

    thread = threading.Thread(target=loop, name="auto-import", daemon=True)
    thread.start()
    return thread


def make_server(config: Config) -> ThreadingHTTPServer:
    app = App(config)
    handler = type("BoundHandler", (Handler,), {"app": app})
    server = ThreadingHTTPServer((config.host, config.port), handler)
    server.app = app  # type: ignore[attr-defined]
    return server
