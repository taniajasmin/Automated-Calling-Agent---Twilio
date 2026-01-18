# Twilio Outbound Dialer

A FastAPI-based automated outbound calling system for a system in Australia to contact pet owners about payment updates.  
The system dials contacts from an uploaded CSV, plays a personalized greeting + pre-recorded message using ElevenLabs TTS, and transfers interested callers to a human agent.

## Features

- Upload daily contact list via CSV (columns: `Client`, `Name`, `Phone`)
- Sequential outbound calling with rate limiting (one call at a time)
- Personalized "Hello [Name]" greeting generated via ElevenLabs TTS
- Long common message played as pre-generated MP3
- Speech & DTMF input detection ("transfer me" or press 1)
- Transfer to human agent 
- Call outcome tracking: `no_answer`, `answered_no_transfer`, `successfully_transferred`
- Automatic CSV result generation with outcome column
- Simple HTML frontend for upload & start

## Tech Stack

- **Backend**: FastAPI
- **Telephony**: Twilio (outbound calls + TwiML)
- **Text-to-Speech**: ElevenLabs
- **Frontend**: Basic HTML + JavaScript
- **Storage**: CSV (input), JSON (temp results), MP3 (audio files)

## Prerequisites

- Python 3.9+
- Twilio account (Account SID, Auth Token, Twilio phone number)
- ElevenLabs account & API key + Voice ID
- ngrok or public server (for Twilio webhooks)


## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/vetpay-outbound-dialer.git
   cd vetpay-outbound-dialer
   ```

2. Create virtual environment & install dependencies:
```Bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install fastapi uvicorn twilio python-multipart requests
```

3. Create config.py in the root directory:
```Python
TWILIO_ACCOUNT_SID = "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
TWILIO_AUTH_TOKEN  = "auth_token"
TWILIO_PHONE_NUMBER = "+614xxxxxxxx"      # Twilio number
BASE_URL = "https://your-ngrok-url.ngrok.io"   # Must be https
ELEVENLABS_API_KEY = "your_elevenlabs_key"
VOICE_ID = "your_voice_id"                # e.g. "Rachel", "Adam", custom voice
```

4. Create folders (automatically created on startup, but you can do it manually):
```text
audio/
output_results/
```

## Usage

1. Start the server
```Bash
uvicorn main:app --reload --port 8000
```

2. Expose locally with ngrok (recommended for testing)
```Bash
ngrok http 8000
```
Copy the https URL and update BASE_URL in config.py.

3. Open the web interface
```text
http://127.0.0.1:8000/index.html
```
Or use the ngrok URL.

4. Workflow
Upload a CSV file with columns: Client, Name, Phone
Click Start Calls
System dials contacts one by one
Results are saved in output_results/call_results_YYYYMMDD_HHMMSS.csv


## Example CSV format (contacts.csv)
```csv
Client,Name,Phone
C001,John Doe,+614123456__
C002,Emma Smith,+614876543__
C003,Alex Tan,+88017123456__
```


## Project Structure
```text
vetpay-outbound-dialer/
├── main.py             # FastAPI application
├── config.py           # (create yourself) credentials
├── index.html          # Simple frontend
├── contacts.csv        # (uploaded)
├── call_results.json   # (temporary results)
├── audio/              # TTS audio files
│   ├── common_message.mp3
│   ├── hello_<client>.mp3
│   ├── please_hold.mp3
│   ├── goodbye.mp3
│   └── thank_you_goodbye.mp3
└── output_results/     # Final CSVs with "Response" column
```


## Important Notes

- Phone normalization: Handles BD (+880) and AU (+61) formats, strips spaces, etc.
- Rate limiting: Calls are made sequentially with a queue to avoid Twilio rate limits.
- Audio generation: Common message is generated once. Short "Hello [name]" is generated per contact if missing.
- Twilio status callbacks: Only completed events are processed.
- No duplicate transfers: If a call was already marked as transferred, status callback won't overwrite it.
- Future Improvements
- Add real-time progress dashboard
- Support retry for busy/no-answer calls
- Add call recording
- Better error handling & logging
- Docker support
- Authentication on API endpoints
