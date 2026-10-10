# AgentProcure API: LangGraph workflow + CrewAI crew + RAG Policy Advisor behind FastAPI
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CREWAI_DISABLE_TELEMETRY=true \
    OTEL_SDK_DISABLED=true \
    CREWAI_TRACING_ENABLED=false

WORKDIR /app

# Dependencies first, so code changes do not reinstall them
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY agentprocure ./agentprocure
COPY evals ./evals
COPY tests ./tests
COPY run_demo.py pytest.ini ./

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=4)"

CMD ["uvicorn", "agentprocure.api:app", "--host", "0.0.0.0", "--port", "8000"]
