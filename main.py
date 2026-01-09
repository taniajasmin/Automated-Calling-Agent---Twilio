from fastapi import FastAPI, UploadFile, Request
from fastapi.responses import Response
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Gather
import csv
import json
import time
import os
from datetime import datetime

from config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_PHONE_NUMBER,
    BASE_URL
)

app = FastAPI(title="VetPay Outbound Dialer")

twilio = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

HUMAN_AGENT_NUMBER = "+8801335117990"
CONTACT_FILE = "contacts.json"
CALL_RESULTS_FILE = "call_results.json"
CALL_DELAY_SECONDS = 20


# Utils
def save_result(phone, name, result):
    results = {}

    if os.path.exists(CALL_RESULTS_FILE):
        with open(CALL_RESULTS_FILE, "r") as f:
            try:
                results = json.load(f)
            except json.JSONDecodeError:
                pass

    results[phone] = {
        "name": name,
        "phone": phone,
        "result": result,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    with open(CALL_RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)


def get_contact_by_phone(phone):
    if not os.path.exists(CONTACT_FILE):
        return None
    with open(CONTACT_FILE, "r") as f:
        contacts = json.load(f)
    for c in contacts:
        if c["phone"] == phone:
            return c
    return None


# Upload CSV
@app.post("/upload-contacts")
async def upload_contacts(file: UploadFile):
    content = (await file.read()).decode().splitlines()
    reader = csv.DictReader(content)

    if not {"Client", "Name", "Phone"}.issubset(reader.fieldnames):
        return {"error": "CSV must contain Client, Name, Phone"}

    contacts = []
    for row in reader:
        contacts.append({
            "client": row["Client"].strip(),
            "name": row["Name"].strip(),
            "phone": row["Phone"].strip()
        })

    with open(CONTACT_FILE, "w") as f:
        json.dump(contacts, f, indent=2)

    return {"message": "Contacts uploaded", "count": len(contacts)}


# Start calls
@app.post("/start-calls")
def start_calls():
    if not os.path.exists(CONTACT_FILE):
        return {"error": "Upload CSV first"}

    with open(CONTACT_FILE, "r") as f:
        contacts = json.load(f)

    for contact in contacts:
        print("Calling:", contact["phone"])

        twilio.calls.create(
            to=contact["phone"],
            from_=TWILIO_PHONE_NUMBER,
            url=f"{BASE_URL}/twilio/voice?name={contact['name']}",
            status_callback=f"{BASE_URL}/twilio/status",
            status_callback_event=["completed"]
        )

        time.sleep(CALL_DELAY_SECONDS)

    return {"status": "calling started", "total": len(contacts)}


# Voice greeting
@app.api_route("/twilio/voice", methods=["GET", "POST"])
async def twilio_voice(request: Request):
    name = request.query_params.get("name", "there")

    response = VoiceResponse()
    gather = Gather(
        input="dtmf speech",
        timeout=8,
        num_digits=1,
        action="/twilio/transfer",
        method="POST"
    )

    gather.say(
        f"Hello {name}, this is an automated call from VetPay. "
        "If you would like to speak to our team now, say transfer me or press 1.",
        voice="alice"
    )

    response.append(gather)
    response.say("Thank you for your time. Goodbye.", voice="alice")

    return Response(str(response), media_type="application/xml")



# Transfer handler
@app.post("/twilio/transfer")
async def transfer_call(request: Request):
    data = await request.form()

    phone = data.get("From")
    digits = data.get("Digits")
    speech = (data.get("SpeechResult") or "").lower()

    contact = get_contact_by_phone(phone)

    response = VoiceResponse()

    if digits == "1" or "transfer" in speech:
        if contact:
            save_result(phone, contact["name"], "successfully_transferred")

        response.say(
            "Please hold while I transfer you to a VetPay representative.",
            voice="alice"
        )
        response.dial(HUMAN_AGENT_NUMBER)
    else:
        response.say("Goodbye.", voice="alice")

    return Response(str(response), media_type="application/xml")


# Call status (no answer / no transfer)
@app.post("/twilio/status")
async def call_status(request: Request):
    data = await request.form()

    phone = data.get("To")
    status = data.get("CallStatus")
    duration = int(data.get("CallDuration") or 0)

    contact = get_contact_by_phone(phone)
    if not contact:
        return "ok"

    # If already transferred, do not overwrite
    if os.path.exists(CALL_RESULTS_FILE):
        with open(CALL_RESULTS_FILE, "r") as f:
            results = json.load(f)
            if phone in results and results[phone]["result"] == "successfully_transferred":
                return "ok"

    if status == "completed" and duration == 0:
        save_result(phone, contact["name"], "no_answer")

    elif status == "completed" and duration > 0:
        save_result(phone, contact["name"], "no_transfer")

    return "ok"
