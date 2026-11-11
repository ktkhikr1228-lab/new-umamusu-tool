"""設定の読み込み。config.toml(任意)と既定値をまとめる。"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

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


def _path(value: object, base: Path) -> Path:
    path = Path(str(value)).expanduser()
    return path if path.is_absolute() else base / path


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
    )
