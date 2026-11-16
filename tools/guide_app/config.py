"""設定の読み込み。config.toml(任意)と既定値をまとめる。"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .extract import Reader

APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parents[1]
DEFAULT_CONFIG_PATH = APP_DIR / "config.toml"
DEFAULT_DATA_ROOT = Path("/home/katao/uma-guide-data")


@dataclass(frozen=True)
class Config:
    data_root: Path
    extracted_dir: Path
    screenshots_dir: Path
    db_path: Path
    skill_master_path: Path
    host: str = "0.0.0.0"
    port: int = 8090
    import_interval: int = 300  # 抽出CSVを自動で取り込む間隔(秒)。0で無効
    token_file: Path = Path("~/.config/uma-tool/github_token")  # Actions起動用(既存のものを使う)
    race_data_url: str = ""  # 空ならGitHub mainの race_data.json
    inbox_dir: Path = Path("inbox")  # 撮影画像の置き場所(<イベント>/<脚質>/<区分>/)
    readers: tuple[Reader, ...] = ()  # 読み取りに使うモデル(2つ以上で多数決)


def _path(value: object, base: Path) -> Path:
    path = Path(str(value)).expanduser()
    return path if path.is_absolute() else base / path


def _readers(raw: object, base: Path) -> tuple[Reader, ...]:
    readers = []
    for item in raw if isinstance(raw, list) else []:
        missing = [k for k in ("name", "base_url", "model") if not item.get(k)]
        if missing:
            raise ValueError(f"[[readers]] に {', '.join(missing)} がありません")
        if not item.get("key_file") and not item.get("key_env"):
            raise ValueError(f"[[readers]] {item['name']}: key_file か key_env のどちらかが必要です")
        readers.append(Reader(
            name=str(item["name"]), base_url=str(item["base_url"]), model=str(item["model"]),
            key_file=_path(item["key_file"], base) if item.get("key_file") else None,
            key_env=str(item.get("key_env", "")),
            min_interval=float(item.get("min_interval", 0)), timeout=int(item.get("timeout", 120)),
        ))
    if len({r.name for r in readers}) != len(readers):
        raise ValueError("[[readers]] の name が重複しています")
    return tuple(readers)


def load_config(path: Path | None = None, overrides: dict | None = None) -> Config:
    """設定ファイルを読む。path未指定なら GUIDE_APP_CONFIG → tools/guide_app/config.toml の順。"""
    if path is None and os.environ.get("GUIDE_APP_CONFIG"):
        path = Path(os.environ["GUIDE_APP_CONFIG"])
    if path is None:
        path = DEFAULT_CONFIG_PATH if DEFAULT_CONFIG_PATH.exists() else None
    raw: dict = {}
    if path is not None:
        with Path(path).open("rb") as f:
            raw = tomllib.load(f)
    raw.update({k: v for k, v in (overrides or {}).items() if v is not None})

    base = Path(path).resolve().parent if path is not None else Path.cwd()
    data_root = _path(raw.get("data_root", DEFAULT_DATA_ROOT), base)
    screenshots_dir = _path(raw.get("screenshots_dir", data_root / "screenshots"), base)
    return Config(
        data_root=data_root,
        extracted_dir=_path(raw.get("extracted_dir", data_root / "extracted"), base),
        screenshots_dir=_path(raw.get("screenshots_dir", data_root / "screenshots"), base),
        db_path=_path(raw.get("db_path", data_root / "guide_app" / "guide.sqlite3"), base),
        skill_master_path=_path(
            raw.get("skill_master_path", REPO_ROOT / "frontend" / "src" / "data" / "skill_master.json"), base
        ),
        host=str(raw.get("host", "0.0.0.0")),
        port=int(raw.get("port", 8090)),
        import_interval=int(raw.get("import_interval", 300)),
        token_file=Path(str(raw.get("token_file", "~/.config/uma-tool/github_token"))).expanduser(),
        race_data_url=str(raw.get("race_data_url", "")),
        inbox_dir=_path(raw.get("inbox_dir", screenshots_dir / "inbox"), base),
        readers=_readers(raw.get("readers"), base),
    )
