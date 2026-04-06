import logging

import google.generativeai as genai


logger = logging.getLogger("talk_trace_ai")


def generate_ai_response(prompt, model_name, api_key, log_message, **context):
    try:
        genai.configure(api_key=api_key)
        return genai.GenerativeModel(model_name).generate_content(prompt).text
    except Exception:
        logger.exception("%s (context=%s)", log_message, context)
        return None
