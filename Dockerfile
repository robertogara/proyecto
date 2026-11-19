FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY ingesta_ica.py ./
CMD ["python", "ingesta_ica.py"]
