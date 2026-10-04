FROM python:3.12-slim

WORKDIR /code
ENV PYTHONPATH=/code \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py errors.py ./
COPY app ./app
COPY worker ./worker
COPY frontend ./frontend
COPY tools ./tools
COPY middleware ./middleware
COPY contracts ./contracts

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
