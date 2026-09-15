FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install FFmpeg and basic tools
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ffmpeg \
       curl \
       ca-certificates \
       unzip \
    && rm -rf /var/lib/apt/lists/*

# Install Deno
RUN curl -fsSL https://deno.land/install.sh | sh

ENV DENO_DIR=/root/.cache/deno
ENV PATH="/root/.deno/bin:${PATH}"

# Install yt-dlp
RUN pip install --no-cache-dir -U yt-dlp

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

EXPOSE 10000

CMD ["python", "server.py"]
