"""과정 루트에서 실행합니다: python -m app.database.init_db --app-dir 방식이 아닌 별도 스크립트입니다."""

import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import psycopg  # noqa: E402

from app.core.config import settings  # noqa: E402


def main() -> None:
    sql_path = Path(__file__).resolve().parents[3] / "sql" / "001_evaluation_schema.sql"
    with psycopg.connect(settings.database_url) as database:
        database.execute(sql_path.read_text(encoding="utf-8"))
    print("mini_multi_agent_07 Schema와 평가 기준 Seed가 준비되었습니다.")


if __name__ == "__main__":
    main()
