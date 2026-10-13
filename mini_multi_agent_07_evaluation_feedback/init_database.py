"""PostgreSQL에 Mini 07 Schema와 평가 기준 Seed를 준비합니다.

기존 수업 명령과의 호환을 위해 남겨 둔 실행 파일입니다. 실제 SQL 적용 로직은
`sql/apply_schema.py`에 있으므로, 새로 보는 학생은 그 파일을 먼저 확인하면 됩니다.
"""

from sql.apply_schema import main


if __name__ == "__main__":
    main()
