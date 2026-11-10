"""`python3 tools/guide_app <コマンド>` で起動するための入口。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from guide_app.cli import main  # noqa: E402

raise SystemExit(main())
