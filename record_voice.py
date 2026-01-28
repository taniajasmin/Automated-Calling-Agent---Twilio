import os
import requests
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

if not ELEVENLABS_API_KEY:
    raise RuntimeError("ELEVENLABS_API_KEY not found in .env file")

VOICE_ID = "snyKKuaGYk1VUEh42zbW"
OUTPUT_FILE = "record.mp3"

SCRIPT_TEXT = """
Hello there, this is an automated call from VetPay.
It looks like we may have incorrect payment details on file.
Please visit vetpay.com.au to update your information.
Thank you, and we hope your pet is doing well.
"""

# ==============================
# TEXT TO SPEECH
# ==============================

def generate_tts_mp3():
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"

    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg"
    }

    payload = {
        "text": SCRIPT_TEXT.strip(),
        "model_id": "eleven_monolingual_v1",
        "voice_settings": {
            "stability": 0.45,
            "similarity_boost": 0.75
        }
    }

    response = requests.post(url, headers=headers, json=payload)

    if response.status_code != 200:
        raise RuntimeError(
            f"TTS failed ({response.status_code}): {response.text}"
        )

    with open(OUTPUT_FILE, "wb") as f:
        f.write(response.content)

    print(f"Audio generated successfully: {OUTPUT_FILE}")


if __name__ == "__main__":
    generate_tts_mp3()
