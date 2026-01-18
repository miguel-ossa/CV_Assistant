# config.py
import os
from dotenv import load_dotenv
from collections import defaultdict

load_dotenv(override=True)
EMAIL_ALERTS_ENABLED = os.getenv("EMAIL_ALERTS_ENABLED")
MAX_TOKENS_PER_IP = 5_000
token_usage = defaultdict(int)