FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# 1. On force d'abord l'installation de PyTorch en version CPU (~180 Mo au lieu de 780 Mo)
RUN pip install --no-cache-dir torch==2.3.0 --index-url https://download.pytorch.org/whl/cpu

# 2. On installe le reste des dépendances (pip verra que torch est déjà là et ne le re-téléchargera pas)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Préchargement des modèles au build
RUN python -c "from sentence_transformers import SentenceTransformer; \
               SentenceTransformer('all-MiniLM-L6-v2')"
RUN python -c "from sentence_transformers import CrossEncoder; \
               CrossEncoder('cross-encoder/mmarco-mMiniLMv2-L12-H384-v1')"

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-exclude", ".venv"]