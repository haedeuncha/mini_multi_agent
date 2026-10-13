r"""SQL 폴더의 스키마 파일을 PostgreSQL에 적용합니다.

실행 명령:
    cd C:\mini_multi_agent\mini_multi_agent_07_evaluation_feedback
    .\.venv\Scripts\Activate.ps1
    python .\sql\apply_schema.py

이 프로그램은 `.env`의 DATABASE_URL을 읽고 `001_evaluation_schema.sql`을 실행합니다.
수업에서는 테이블을 직접 하나씩 복사하기보다 이 파일로 스키마를 한 번에 적용합니다.
"""

from pathlib import Path
import os

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SQL_FILE = Path(__file__).resolve().parent / "001_evaluation_schema.sql"


def main() -> None:
    load_dotenv(ROOT / ".env")
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql://agent_user:agent_pwd@127.0.0.1:5433/agent_db",
    )
    sql = SQL_FILE.read_text(encoding="utf-8")
    with psycopg.connect(database_url) as database:
        database.execute(sql)
    print(f"스키마 적용 완료: {SQL_FILE.name}")


if __name__ == "__main__":
    main()
