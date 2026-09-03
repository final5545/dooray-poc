FROM python:3.11-slim

WORKDIR /app

# 런타임 의존성은 셋뿐이다 (SDK 불필요)
RUN pip install --no-cache-dir requests certifi python-dotenv

COPY crm/ ./crm/
COPY support/ ./support/
COPY routing.py ./
COPY standalone/command_server.py standalone/mock_crm.py ./standalone/

EXPOSE 8910
CMD ["python", "-u", "standalone/command_server.py", "8910"]
