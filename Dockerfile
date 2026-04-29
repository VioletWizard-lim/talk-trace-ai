FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN mkdir -p .streamlit

CMD mkdir -p .streamlit && \
    echo "[default]" > .streamlit/secrets.toml && \
    echo "SUPABASE_URL = \"$SUPABASE_URL\"" >> .streamlit/secrets.toml && \
    echo "SUPABASE_KEY = \"$SUPABASE_KEY\"" >> .streamlit/secrets.toml && \
    echo "SUPABASE_APP_EMAIL = \"$SUPABASE_APP_EMAIL\"" >> .streamlit/secrets.toml && \
    echo "SUPABASE_APP_PASSWORD = \"$SUPABASE_APP_PASSWORD\"" >> .streamlit/secrets.toml && \
    echo "GEMINI_API_KEY = \"$GEMINI_API_KEY\"" >> .streamlit/secrets.toml && \
    streamlit run app.py --server.port=7860 --server.address=0.0.0.0
