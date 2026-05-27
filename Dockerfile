FROM python:3.11-slim

# Dependências do sistema para o Playwright/Chromium
RUN apt-get update && apt-get install -y \
    wget curl gnupg ca-certificates \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instala o Chromium do Playwright
RUN playwright install chromium
RUN playwright install-deps chromium

COPY . .

# Cria diretórios de runtime
RUN mkdir -p data logs

EXPOSE 8000

CMD ["python", "rpa.py"]
