import os
from dotenv import load_dotenv

load_dotenv()

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "snyKKuaGYk1VUEh42zbW")

BASE_URL = os.getenv("BASE_URL")  


HUMAN_AGENT_NUMBER = os.getenv("HUMAN_AGENT_NUMBER")
COMMON_MESSAGE_TEXT = os.getenv("COMMON_MESSAGE_TEXT")

# ... Update code ...
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "a_very_secret_random_string_change_this")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8 hours
