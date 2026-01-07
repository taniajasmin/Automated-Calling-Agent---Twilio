from fastapi import FastAPI, UploadFile, Request, File
from fastapi.responses import Response, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Gather
import csv
import json
import time
import os
from io import StringIO
from datetime import datetime

from config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_PHONE_NUMBER,
    BASE_URL
)

app = FastAPI(title="VetPay Outbound Dialer")

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

twilio = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

HUMAN_AGENT_NUMBER = "+8801335117990"  
CONTACT_FILE = "contacts.json"
CALL_OUTCOME_FILE = "call_outcomes.json"
CALL_DELAY_SECONDS = 10  


# -----------------------------
# Utils
# -----------------------------
def sanitize_phone(raw: str) -> str:
    if not raw:
        return ""
    phone = raw.strip().replace("'", "").replace('"', "").replace(" ", "")
    if phone.startswith("00"):
        phone = "+" + phone[2:]
    if not phone.startswith("+"):
        phone = "+" + phone
    return phone


def save_call_outcome(phone: str, client_id: str, name: str, outcome: str, duration: int = 0):
    results = {}

    if os.path.exists(CALL_OUTCOME_FILE):
        with open(CALL_OUTCOME_FILE, "r") as f:
            try:
                results = json.load(f)
            except json.JSONDecodeError:
                pass

    results[phone] = {
        "client_id": client_id,
        "name": name,
        "phone": phone,
        "outcome": outcome,
        "duration_seconds": duration,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    with open(CALL_OUTCOME_FILE, "w") as f:
        json.dump(results, f, indent=2)


def send_voicemail_mms(phone: str):
    media_url = f"{BASE_URL}/media/record_message.mp3"
    print(f"\n📤 SENDING VOICEMAIL MMS")
    print(f"   To: {phone}")
    print(f"   Media URL: {media_url}")
    
    try:
        message = twilio.messages.create(
            to=phone,
            from_=TWILIO_PHONE_NUMBER,
            body="We tried calling you from VetPay. Please listen to this short message.",
            media_url=[media_url]
        )
        print(f"✅ MMS SENT!")
        print(f"   Message SID: {message.sid}")
        print(f"   Status: {message.status}\n")
        return True
    except Exception as e:
        print(f"❌ MMS FAILED: {str(e)}\n")
        return False


# -----------------------------
# Serve recorded audio
# -----------------------------
@app.get("/media/record_message.mp3")
def get_recorded_message():
    return FileResponse(
        "record_message.mp3",
        media_type="audio/mpeg",
        filename="record_message.mp3"
    )


# -----------------------------
# Serve Dashboard HTML
# -----------------------------
@app.get("/")
def dashboard():
    return FileResponse("dashboard.html")


# -----------------------------
# Upload CSV
# -----------------------------
@app.post("/upload-contacts")
async def upload_contacts(file: UploadFile = File(...)):
    content = (await file.read()).decode().splitlines()
    reader = csv.DictReader(content)

    # Check required columns
    required_cols = {"Client", "Name", "Phone"}
    if not required_cols.issubset(set(reader.fieldnames)):
        return JSONResponse(
            {"error": f"CSV must contain: Client, Name, Phone"},
            status_code=400
        )

    contacts = []
    for row in reader:
        phone = sanitize_phone(row["Phone"])
        if phone:  # Only add if phone is valid
            contacts.append({
                "client_id": row["Client"].strip(),
                "name": row["Name"].strip(),
                "phone": phone
            })

    with open(CONTACT_FILE, "w") as f:
        json.dump(contacts, f, indent=2)

    return {"message": "Contacts uploaded successfully", "count": len(contacts)}


# -----------------------------
# Start outbound calls
# -----------------------------
@app.post("/start-calls")
def start_calls():
    if not os.path.exists(CONTACT_FILE):
        return JSONResponse({"error": "Please upload CSV first"}, status_code=400)

    with open(CONTACT_FILE, "r") as f:
        contacts = json.load(f)

    if not contacts:
        return JSONResponse({"error": "No contacts to call"}, status_code=400)

    print(f"\n🚀 STARTING CALLS - Total: {len(contacts)}")
    print(f"⏱️  Delay between calls: {CALL_DELAY_SECONDS} seconds\n")

    for i, c in enumerate(contacts, 1):
        client_id = c.get('client_id', '')
        name = c.get('name', '')
        phone = c.get('phone', '')
        
        print(f"📞 Call {i}/{len(contacts)}: {name} ({phone})")
        
        try:
            call = twilio.calls.create(
                to=phone,
                from_=TWILIO_PHONE_NUMBER,
                url=f"{BASE_URL}/twilio/voice?client_id={client_id}&name={name}&phone={phone}",
                status_callback=f"{BASE_URL}/twilio/status",
                status_callback_event=["initiated", "ringing", "answered", "completed"],
                machine_detection="Enable",
                async_amd="true",
                async_amd_status_callback=f"{BASE_URL}/twilio/amd-status",
                async_amd_status_callback_method="POST"
            )
            print(f"   Call SID: {call.sid}")
        except Exception as e:
            print(f"   ❌ Error: {str(e)}")

        # Wait before next call (except for last one)
        if i < len(contacts):
            print(f"   ⏳ Waiting {CALL_DELAY_SECONDS} seconds...\n")
            time.sleep(CALL_DELAY_SECONDS)

    return {"status": "Calling started", "total": len(contacts)}


# -----------------------------
# Voice greeting (Australian female voice)
# -----------------------------
@app.api_route("/twilio/voice", methods=["GET", "POST"])
async def twilio_voice(request: Request):
    client_id = request.query_params.get("client_id", "")
    name = request.query_params.get("name", "there")
    phone = request.query_params.get("phone", "")

    print(f"\n🎙️  VOICE CALL ANSWERED")
    print(f"   Client: {name} ({client_id})")
    print(f"   Phone: {phone}\n")

    response = VoiceResponse()
    gather = Gather(
        input="dtmf speech",
        timeout=10,
        num_digits=1,
        action=f"{BASE_URL}/twilio/transfer?client_id={client_id}&name={name}&phone={phone}",
        method="POST",
        speech_timeout="auto"
    )

    # Australian female voice greeting
    gather.say(
        f"Hello {name}. This is an automated call from VetPay. "
        "It looks like we may have the wrong payment details for you. "
        "If you'd like to update them and speak to our team now, say transfer me or press 1. "
        "Alternatively you can update your details on your portal at vetpay dot com dot au. "
        "We hope we've been able to assist with your pets treatment. Thank you.",
        voice="Polly.Nicole",  # Australian female voice
        language="en-AU"
    )

    response.append(gather)
    response.say("Thank you. Goodbye.", voice="Polly.Nicole", language="en-AU")

    return Response(str(response), media_type="application/xml")


# -----------------------------
# Transfer handler
# -----------------------------
@app.post("/twilio/transfer")
async def transfer_call(request: Request):
    data = await request.form()
    client_id = request.query_params.get("client_id", "")
    name = request.query_params.get("name", "")
    phone = sanitize_phone(request.query_params.get("phone", ""))

    speech = data.get("SpeechResult", "").lower()
    digits = data.get("Digits", "")

    print(f"\n🔄 TRANSFER REQUESTED")
    print(f"   Client: {name} ({client_id})")
    print(f"   Speech: {speech}")
    print(f"   Digits: {digits}\n")

    # Check if user wants transfer
    if "transfer" in speech or digits == "1":
        save_call_outcome(phone, client_id, name, "transferred_to_human")

        response = VoiceResponse()
        response.say(
            "Please hold for a moment while I transfer you to a VetPay representative now. Thank you for your time.",
            voice="Polly.Nicole",
            language="en-AU"
        )
        response.dial(HUMAN_AGENT_NUMBER)
        
        print(f"✅ Transferred to human agent\n")
        return Response(str(response), media_type="application/xml")
    else:
        response = VoiceResponse()
        response.say("Thank you. Goodbye.", voice="Polly.Nicole", language="en-AU")
        return Response(str(response), media_type="application/xml")


# -----------------------------
# AMD (Answering Machine Detection) Status
# -----------------------------
@app.post("/twilio/amd-status")
async def amd_status(request: Request):
    data = await request.form()
    
    answered_by = data.get("AnsweredBy")
    phone = sanitize_phone(data.get("To", ""))
    
    print(f"\n🤖 AMD DETECTION")
    print(f"   Phone: {phone}")
    print(f"   Answered By: {answered_by}\n")

    # Get contact info
    contact_info = get_contact_by_phone(phone)
    
    if answered_by in ["machine_start", "machine_end_beep", "machine_end_silence", "machine_end_other"]:
        print(f"📞 VOICEMAIL DETECTED - Sending MMS\n")
        if contact_info:
            save_call_outcome(phone, contact_info["client_id"], contact_info["name"], "left_voicemail")
        send_voicemail_mms(phone)

    return "ok"


# -----------------------------
# Call status callback
# -----------------------------
@app.post("/twilio/status")
async def call_status(request: Request):
    data = await request.form()

    phone = sanitize_phone(data.get("To", ""))
    status = data.get("CallStatus")
    duration = int(data.get("CallDuration") or 0)

    print(f"\n📊 CALL STATUS UPDATE")
    print(f"   Phone: {phone}")
    print(f"   Status: {status}")
    print(f"   Duration: {duration}s\n")

    # Get contact info
    contact_info = get_contact_by_phone(phone)
    if not contact_info:
        return "ok"

    existing = {}
    if os.path.exists(CALL_OUTCOME_FILE):
        with open(CALL_OUTCOME_FILE, "r") as f:
            try:
                existing = json.load(f)
            except json.JSONDecodeError:
                pass

    # Never overwrite transfers or voicemails
    if phone in existing and existing[phone]["outcome"] in ["transferred_to_human", "left_voicemail"]:
        return "ok"

    # NO ANSWER - Send voicemail MMS
    if status == "completed" and duration == 0:
        print(f"📵 NO ANSWER - Sending voicemail MMS\n")
        save_call_outcome(phone, contact_info["client_id"], contact_info["name"], "no_answer")
        send_voicemail_mms(phone)
        return "ok"

    # ANSWERED BUT NO ACTION
    if status == "completed" and duration > 0:
        save_call_outcome(phone, contact_info["client_id"], contact_info["name"], "answered_no_action", duration)

    return "ok"


# -----------------------------
# Helper function to get contact by phone
# -----------------------------
def get_contact_by_phone(phone: str):
    if not os.path.exists(CONTACT_FILE):
        return None
    
    with open(CONTACT_FILE, "r") as f:
        contacts = json.load(f)
    
    for contact in contacts:
        if contact["phone"] == phone:
            return contact
    return None


# -----------------------------
# Get call results (JSON)
# -----------------------------
@app.get("/call-results")
def get_call_results():
    if not os.path.exists(CALL_OUTCOME_FILE):
        return []

    with open(CALL_OUTCOME_FILE, "r") as f:
        data = json.load(f)

    LABELS = {
        "no_answer": "No answer",
        "left_voicemail": "Left voicemail",
        "transferred_to_human": "Transferred to human",
        "answered_no_action": "Answered (no action)"
    }

    results = []
    for phone, info in data.items():
        results.append({
            "client_id": info.get("client_id", ""),
            "name": info.get("name", ""),
            "phone": phone,
            "call_response": LABELS.get(info["outcome"], info["outcome"]),
            "duration_seconds": info.get("duration_seconds", 0),
            "timestamp": info["timestamp"]
        })

    return results


# -----------------------------
# Download results as CSV
# -----------------------------
@app.get("/download-results-csv")
def download_results_csv():
    results = get_call_results()
    
    if not results:
        return Response("No results yet", media_type="text/plain")

    # Create CSV
    output = StringIO()
    fieldnames = ["client_id", "name", "phone", "call_response", "duration_seconds", "timestamp"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    
    # Write header
    writer.writeheader()
    
    # Write rows with proper column names
    for row in results:
        writer.writerow({
            "client_id": row["client_id"],
            "name": row["name"],
            "phone": row["phone"],
            "call_response": row["call_response"],
            "duration_seconds": row["duration_seconds"],
            "timestamp": row["timestamp"]
        })

    # Generate filename with timestamp
    filename = f"vetpay_call_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# -----------------------------
# Clear results
# -----------------------------
@app.post("/clear-results")
def clear_results():
    if os.path.exists(CALL_OUTCOME_FILE):
        os.remove(CALL_OUTCOME_FILE)
    if os.path.exists(CONTACT_FILE):
        os.remove(CONTACT_FILE)
    return {"message": "Results cleared"}
