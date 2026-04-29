#!/bin/bash
mkdir -p .streamlit
cat > .streamlit/secrets.toml << EOF
[default]
SUPABASE_URL = "${SUPABASE_URL}"
SUPABASE_KEY = "${SUPABASE_KEY}"
SUPABASE_APP_EMAIL = "${SUPABASE_APP_EMAIL}"
SUPABASE_APP_PASSWORD = "${SUPABASE_APP_PASSWORD}"
GEMINI_API_KEY = "${GEMINI_API_KEY}"
EOF
streamlit run app.py --server.port=7860 --server.address=0.0.0.0
