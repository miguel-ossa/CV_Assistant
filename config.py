# config.py
import os
from dotenv import load_dotenv

load_dotenv(override=True)
EMAIL_ALERTS_ENABLED = os.getenv("EMAIL_ALERTS_ENABLED")
