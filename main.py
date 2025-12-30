from fastapi import FastAPI, UploadFile, Request
from fastapi.responses import Response
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse
import csv, json
import time

from config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_PHONE_NUMBER,
    BASE_URL
)

app = FastAPI(title="VetPay Outbound Call Agent")

twilio_client = Client(
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN
)

CONTACT_FILE = "contacts.json"

# -----------------------------
# 1. Upload daily contact list
# -----------------------------
@app.post("/upload-contacts")
async def upload_contacts(file: UploadFile):
    content = await file.read()
    decoded = content.decode().splitlines()
    reader = csv.DictReader(decoded)

    contacts = []
    for row in reader:
        contacts.append({
            "name": row["name"],
            "phone": row["phone"]
        })

    with open(CONTACT_FILE, "w") as f:
        json.dump(contacts, f)

    return {
        "message": "Contacts uploaded",
        "count": len(contacts)
    }

# -----------------------------
# 2. Start outbound calling

@app.post("/start-calls")
def start_calls():
    try:
        with open(CONTACT_FILE, "r") as f:
            content = f.read().strip()

            if not content:
                return {
                    "error": "Contact list is empty. Please upload CSV first."
                }

            contacts = json.loads(content)

    except FileNotFoundError:
        return {
            "error": "contacts.json not found. Upload contacts first."
        }
    except json.JSONDecodeError:
        return {
            "error": "contacts.json is invalid. Re-upload CSV."
        }

    for contact in contacts:
        twilio_client.calls.create(
            to=contact["phone"],
            from_=TWILIO_PHONE_NUMBER,
            url=f"{BASE_URL}/twilio/voice?name={contact['name']}",
            status_callback=f"{BASE_URL}/twilio/status",
            status_callback_event=["completed"]
        )
        time.sleep(3)

    return {
        "status": "calling started",
        "total": len(contacts)
    }

@app.post("/twilio/status")
async def call_status(request: Request):
    data = await request.form()
    status = data.get("CallStatus")
    to_number = data.get("To")

    result = {
        "to": to_number,
        "status": status,
        "timestamp": data.get("Timestamp"),
        "sip_code": data.get("SipResponseCode")
    }

    # append to log file
    with open("call_results.json", "a") as f:
        f.write(json.dumps(result) + "\n")

    print("Call result:", result)
    return "ok"



# -----------------------------
# 3. Twilio voice webhook
# -----------------------------
@app.get("/twilio/voice")
def twilio_voice(name: str):
    response = VoiceResponse()

    response.say(
        f"Hello {name}. This is an automated call from VetPay regarding your payment details. "
        "This is a reminder that your account requires attention. "
        "Please expect a follow-up message shortly.",
        voice="alice"
    )

    return Response(str(response), media_type="application/xml")

# -----------------------------
# 4. Call status tracking
# -----------------------------
@app.post("/twilio/status")
async def call_status(request: Request):
    data = await request.form()
    print("Call status:", dict(data))
    return "ok"
