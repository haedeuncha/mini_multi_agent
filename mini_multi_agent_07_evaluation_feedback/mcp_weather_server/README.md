# Weather MCP Server

이 폴더는 `mini_multi_agent_07_evaluation_feedback`에서 사용하는 실제 MCP 서버입니다.

## 실행

```powershell
cd C:\mini_multi_agent\mini_multi_agent_07_evaluation_feedback
.\.venv\Scripts\Activate.ps1
python .\mcp_weather_server\main.py
```

## Endpoint

```text
http://127.0.0.1:18012/mcp
```

이 서버는 `FastMCP`의 `streamable-http` transport로 실행됩니다.
