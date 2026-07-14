FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py .
COPY database.py .
COPY auth.py .
COPY pipeline.py .
COPY llm_client.py .
COPY data_source.py .
COPY news_fetcher.py .
COPY chat_engine.py .
COPY deep_analysis/ ./deep_analysis/

COPY web/ ./web/
RUN mkdir -p results data deep_work outputs

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000"]