FROM ghcr.io/violetwizard-lim/talk-trace-ai:base

WORKDIR /app
COPY . .

EXPOSE 7860

CMD ["streamlit", "run", "app.py", "--server.port=7860", "--server.address=0.0.0.0"]
