FROM ghcr.io/violetwizard-lim/talk-trace-ai:base

WORKDIR /app
COPY . .

RUN apt-get update && apt-get install -y --no-install-recommends fonts-nanum \
    && rm -rf /var/lib/apt/lists/*

EXPOSE 7860

CMD ["streamlit", "run", "app.py", "--server.port=7860", "--server.address=0.0.0.0"]
