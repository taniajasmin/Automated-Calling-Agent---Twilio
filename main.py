# from fastapi import FastAPI, UploadFile
# from fastapi.responses import Response
# from fastapi import Request
# from twilio.rest import Client
# from twilio.twiml.voice_response import VoiceResponse, Gather
# import csv
# import json
# import time
# import os

# from config import (
#     TWILIO_ACCOUNT_SID,
#     TWILIO_AUTH_TOKEN,
#     TWILIO_PHONE_NUMBER,
#     BASE_URL
# )

# app = FastAPI(title="VetPay Outbound Dialer")

# twilio = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# HUMAN_AGENT_NUMBER = "'+8801335117990"
# CONTACT_FILE = "contacts.json"
# CALL_DELAY_SECONDS = 20

# # Upload CSV
# @app.post("/upload-contacts")
# async def upload_contacts(file: UploadFile):
#     content = (await file.read()).decode().splitlines()
#     reader = csv.DictReader(content)

#     required_headers = {"Client", "Name", "Phone"}

#     if not required_headers.issubset(reader.fieldnames):
#         return {
#             "error": "CSV must contain exactly: Client, Name, Phone"
#         }

#     contacts = []

#     for row in reader:
#         contacts.append({
#             "client": row["Client"].strip(),
#             "name": row["Name"].strip(),
#             "phone": row["Phone"].strip()
#         })

#     with open(CONTACT_FILE, "w") as f:
#         json.dump(contacts, f, indent=2)

#     return {
#         "message": "Contacts uploaded",
#         "count": len(contacts)
#     }

# # Start calling (one by one)
# @app.post("/start-calls")
# def start_calls():
#     if not os.path.exists(CONTACT_FILE):
#         return {"error": "Upload CSV first"}

#     with open(CONTACT_FILE, "r") as f:
#         contacts = json.load(f)

#     for contact in contacts:
#         print("Calling:", contact["phone"])

#         twilio.calls.create(
#             to=contact["phone"],
#             from_=TWILIO_PHONE_NUMBER,
#             url=f"{BASE_URL}/twilio/voice?name={contact['name']}"
#         )

#         time.sleep(CALL_DELAY_SECONDS)

#     return {
#         "status": "calling started",
#         "total": len(contacts)
#     }

# # Voice greeting
# # @app.api_route("/twilio/voice", methods=["GET", "POST"])
# # def twilio_voice(name: str):
# #     response = VoiceResponse()

# #     response.say(
# #         f"Hello {name}, this is an automated call from VetPay. "
# #         "It looks like we may have the wrong payment details for you. "
# #         "Please log in to your VetPay portal to update them. "
# #         "Thank you.",
# #         voice="alice"
# #     )

# #     return Response(str(response), media_type="application/xml")

# @app.api_route("/twilio/voice", methods=["GET", "POST"])
# async def twilio_voice(request: Request):
#     # get name from query or form
#     name = request.query_params.get("name")
#     if not name:
#         form = await request.form()
#         name = form.get("name", "there")

#     response = VoiceResponse()

#     gather = Gather(
#         input="dtmf speech",
#         timeout=8,
#         num_digits=1,
#         action="/twilio/transfer",
#         method="POST"
#     )

#     gather.say(
#         f"Hello {name}, this is an automated call from VetPay. "
#         "It looks like we may have the wrong payment details for you. "
#         "If you would like to update them and speak to our team now, "
#         "say transfer me or press 1. "
#         "Thank you.",
#         voice="alice"
#     )

#     response.append(gather)

#     # If no input
#     response.say("Thank you for your time. Goodbye.", voice="alice")

#     return Response(str(response), media_type="application/xml")

# @app.post("/twilio/transfer")
# async def transfer_call(request: Request):
#     data = await request.form()

#     digits = data.get("Digits")
#     speech = (data.get("SpeechResult") or "").lower()

#     # determine transfer reason
#     if digits == "1":
#         transfer_reason = "dtmf_1"
#     elif "transfer" in speech:
#         transfer_reason = "voice_transfer_me"
#     else:
#         transfer_reason = "unknown"

#     print("TRANSFER TRIGGERED BY:", transfer_reason)

#     response = VoiceResponse()

#     if transfer_reason in ["dtmf_1", "voice_transfer_me"]:
#         response.say(
#             "Please hold for a moment while I transfer you to a VetPay representative now.",
#             voice="alice"
#         )
#         response.dial(HUMAN_AGENT_NUMBER)
#     else:
#         response.say("Goodbye.", voice="alice")

#     return Response(str(response), media_type="application/xml")



from fastapi import FastAPI, UploadFile
from fastapi.responses import Response
from fastapi import Request
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Gather
import csv
import json
import time
import os

from config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_PHONE_NUMBER,
    BASE_URL
)

app = FastAPI(title="VetPay Outbound Dialer")

twilio = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

HUMAN_AGENT_NUMBER = "'+8801335117990"
CONTACT_FILE = "contacts.json"
CALL_OUTCOME_FILE = "call_outcomes.json"
CALL_DELAY_SECONDS = 60

# Upload CSV
@app.post("/upload-contacts")
async def upload_contacts(file: UploadFile):
    content = (await file.read()).decode().splitlines()
    reader = csv.DictReader(content)

    required_headers = {"Client", "Name", "Phone"}

    if not required_headers.issubset(reader.fieldnames):
        return {
            "error": "CSV must contain exactly: Client, Name, Phone"
        }

    contacts = []

    for row in reader:
        contacts.append({
            "client": row["Client"].strip(),
            "name": row["Name"].strip(),
            "phone": row["Phone"].strip()
        })

    with open(CONTACT_FILE, "w") as f:
        json.dump(contacts, f, indent=2)

    return {
        "message": "Contacts uploaded",
        "count": len(contacts)
    }

# Start calling (one by one)
@app.post("/start-calls")
def start_calls():
    if not os.path.exists(CONTACT_FILE):
        return {"error": "Upload CSV first"}

    with open(CONTACT_FILE, "r") as f:
        contacts = json.load(f)

    for contact in contacts:
        print("Calling:", contact["phone"])

        # twilio.calls.create(
        #     to=contact["phone"],
        #     from_=TWILIO_PHONE_NUMBER,
        #     url=f"{BASE_URL}/twilio/voice?name={contact['name']}"
        # )
        twilio.calls.create(
            to=contact["phone"],
            from_=TWILIO_PHONE_NUMBER,
            url=f"{BASE_URL}/twilio/voice?name={contact['name']}",
            status_callback=f"{BASE_URL}/twilio/status",
            status_callback_event=["completed"]
        )


        time.sleep(CALL_DELAY_SECONDS)

    return {
        "status": "calling started",
        "total": len(contacts)
    }

# Voice greeting
# @app.api_route("/twilio/voice", methods=["GET", "POST"])
# def twilio_voice(name: str):
#     response = VoiceResponse()

#     response.say(
#         f"Hello {name}.
#         voice="alice"
#     )

#     return Response(str(response), media_type="application/xml")

@app.api_route("/twilio/voice", methods=["GET", "POST"])
async def twilio_voice(request: Request):
    # get name from query or form
    name = request.query_params.get("name")
    if not name:
        form = await request.form()
        name = form.get("name", "there")

    response = VoiceResponse()

    gather = Gather(
        input="dtmf speech",
        timeout=8,
        num_digits=1,
        # action="/twilio/transfer",
        action=f"{BASE_URL}/twilio/transfer",
        method="POST"
    )

    gather.say(
        f"Hello {name}, this is an automated call from VetPay. "
        "It looks like we may have the wrong payment details for you. "
        "If you would like to update them and speak to our team now, "
        "say transfer me or press 1. "
        "Thank you.",
        voice="alice"
    )

    response.append(gather)

    # If no input
    response.say("Thank you for your time. Goodbye.", voice="alice")

    return Response(str(response), media_type="application/xml")

# @app.post("/twilio/transfer")
# async def transfer_call(request: Request):
#     data = await request.form()

#     digits = data.get("Digits")
#     speech = (data.get("SpeechResult") or "").lower()

#     # determine transfer reason
#     if digits == "1":
#         transfer_reason = "dtmf_1"
#     elif "transfer" in speech:
#         transfer_reason = "voice_transfer_me"
#     else:
#         transfer_reason = "unknown"

#     print("TRANSFER TRIGGERED BY:", transfer_reason)

#     response = VoiceResponse()

#     if transfer_reason in ["dtmf_1", "voice_transfer_me"]:
#         response.say(
#             "Please hold for a moment while I transfer you to a VetPay representative now.",
#             voice="alice"
#         )
#         response.dial(HUMAN_AGENT_NUMBER)
#     else:
#         response.say("Goodbye.", voice="alice")

#     return Response(str(response), media_type="application/xml")

@app.post("/twilio/transfer")
async def transfer_call(request: Request):
    data = await request.form()

    digits = data.get("Digits")
    speech = (data.get("SpeechResult") or "").lower()

    if digits == "1":
        outcome = "transferred_dtmf"
    elif "transfer" in speech:
        outcome = "transferred_voice"
    else:
        outcome = "completed"

    print("CALL OUTCOME:", outcome)

    # save_call_outcome(
    #     phone=data.get("From", "unknown"),
    #     outcome=outcome
    # )
    save_call_outcome(
        phone=data.get("To"),
        outcome=outcome
    )

    response = VoiceResponse()

    if outcome.startswith("transferred"):
        response.say(
            "Please hold for a moment while I transfer you to a VetPay representative now.",
            voice="alice"
        )
        response.dial(HUMAN_AGENT_NUMBER)
    else:
        response.say("Goodbye.", voice="alice")

    return Response(str(response), media_type="application/xml")




def save_call_outcome(phone: str, outcome: str):
    results = {}

    if os.path.exists(CALL_OUTCOME_FILE):
        with open(CALL_OUTCOME_FILE, "r") as f:
            try:
                results = json.load(f)
            except json.JSONDecodeError:
                results = {}

    results[phone] = {
        "outcome": outcome,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }

    with open(CALL_OUTCOME_FILE, "w") as f:
        json.dump(results, f, indent=2)


@app.post("/twilio/status")
async def call_status(request: Request):
    data = await request.form()

    call_status = data.get("CallStatus")
    to_number = data.get("To")

    # load existing outcomes
    existing = {}
    if os.path.exists(CALL_OUTCOME_FILE):
        with open(CALL_OUTCOME_FILE, "r") as f:
            try:
                existing = json.load(f)
            except json.JSONDecodeError:
                existing = {}

    # do NOT overwrite transfers
    if to_number in existing and existing[to_number]["outcome"].startswith("transferred"):
        return "ok"

    if call_status in ["no-answer", "busy", "failed"]:
        save_call_outcome(to_number, call_status)

    elif call_status == "completed" and int(data.get("CallDuration", "0")) > 0:
        save_call_outcome(to_number, "answered_no_action")

    return "ok"
