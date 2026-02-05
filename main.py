from fastapi import FastAPI, UploadFile, Request, BackgroundTasks
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from twilio.rest import Client
from fastapi.middleware.cors import CORSMiddleware
from twilio.twiml.voice_response import VoiceResponse, Gather
from fastapi.responses import FileResponse
import csv
import json
import os
from datetime import datetime
from threading import Lock
import requests
import queue


from config import HUMAN_AGENT_NUMBER, COMMON_MESSAGE_TEXT

from config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_PHONE_NUMBER,
    BASE_URL,
    ELEVENLABS_API_KEY,
    VOICE_ID
)

app = FastAPI(title="VetPay Outbound Dialer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

twilio = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# HUMAN_AGENT_NUMBER = "+8801331756795"

# ─── Paths ────────────────────────────────────────────────────
CONTACTS_CSV     = "contacts.csv"
RESULTS_JSON     = "call_results.json"
OUTPUT_CSV_DIR   = "output_results"
AUDIO_DIR        = "audio"

os.makedirs(OUTPUT_CSV_DIR, exist_ok=True)
os.makedirs(AUDIO_DIR, exist_ok=True)
app.mount("/audio", StaticFiles(directory=AUDIO_DIR), name="audio")

# ─── ElevenLabs TTS ───────────────────────────────────────────
def generate_audio(text: str, output_path: str):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": ELEVENLABS_API_KEY
    }
    payload = {
        "text": text,
        "model_id": "eleven_monolingual_v1", 
        "voice_settings": {
            "stability": 0.45,
            "similarity_boost": 0.75
        }
    }
    resp = requests.post(url, json=payload, headers=headers)
    if resp.status_code == 200:
        with open(output_path, "wb") as f:
            f.write(resp.content)
        print(f"Audio generated: {output_path}")
    else:
        print(f"ElevenLabs failed: {resp.status_code} - {resp.text}")
        raise Exception("TTS generation failed")

# ─── Pre-generate static / common audio files ─────────────────
COMMON_MESSAGE_PATH = os.path.join(AUDIO_DIR, "common_message_v3.mp3")


# COMMON_TEXT = (
#     "This is an automated call from VetPay. "
#     "It looks like we may have the wrong payment details for you. "
#     "If you’d like to update them and speak to our team now, "
#     "say “transfer me” or press 1. "
#     "Alternatively you can update your details on your portal at vetpay.com.au. "
#     "We hope we've been able to assist with your pets treatment. Thank you"
#     "would you like to transfer?"
    
# )

COMMON_TEXT = COMMON_MESSAGE_TEXT

# One-time generation of the long common part
if not os.path.exists(COMMON_MESSAGE_PATH):
    print("Generating common message audio (one-time task)...")
    generate_audio(COMMON_TEXT, COMMON_MESSAGE_PATH)
    print("Common message audio created.")
else:
    print("Common message audio already exists → skipping generation.")

# Other static phrases
static_texts = {
    "thank_you_goodbye_v3": "Thank you for your time. Goodbye.",
    "please_hold_v3": "Please hold while I transfer you to a VetPay representative."
}

for key, txt in static_texts.items():
    path = os.path.join(AUDIO_DIR, f"{key}.mp3")
    if not os.path.exists(path):
        generate_audio(txt, path)

# Queue for sequential calling
call_queue = queue.Queue()
next_call_lock = Lock()
is_calling = False

def start_next_call():
    global is_calling, stop_requested

    if stop_requested:
        print("Stop requested. No more calls will be made.")
        return

    with next_call_lock:
        if is_calling or call_queue.empty():
            return
        is_calling = True

    try:
        phone, name, client_id = call_queue.get_nowait()
        print(f"[OUT] Calling: {phone} ({name}) - Client: {client_id}")

        twilio.calls.create(
            to=phone,
            from_=TWILIO_PHONE_NUMBER,
            url=f"{BASE_URL}/twilio/voice?client={client_id}",
            status_callback=f"{BASE_URL}/twilio/status",
            status_callback_event=["completed"],
        )
    except queue.Empty:
        pass
    finally:
        with next_call_lock:
            is_calling = False


stop_requested = False

# Global state
call_tracker = {
    "total": 0,
    "completed": 0,
    "running": False,
    "lock": Lock()
}

contact_map: dict[str, dict] = {}

def normalize_phone(p: str) -> str:
    if not p:
        return ""
    cleaned = ''.join(c for c in str(p).strip() if c.isdigit() or c == '+')
    if cleaned.count('+') > 1:
        cleaned = '+' + cleaned.replace('+', '')
    if not cleaned.startswith('+'):
        cleaned = '+' + cleaned
    if cleaned.startswith('+88') and len(cleaned) == 13 and cleaned[3] != '0':
        cleaned = '+880' + cleaned[3:]
    print(f"Normalized: '{p}' → '{cleaned}'")
    return cleaned

def load_contacts_to_memory():
    global contact_map
    contact_map.clear()
    if not os.path.exists(CONTACTS_CSV):
        return 0
    count = 0
    with open(CONTACTS_CSV, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            phone = normalize_phone(row.get("Phone", ""))
            if phone:
                contact_map[phone] = {
                    "name": row.get("Name", "").strip() or "there",
                    "client": row.get("Client", "").strip()
                }
                print(f"Stored contact: {phone} → {contact_map[phone]}")
                count += 1
    return count

# Utils
def save_result(phone: str, name: str, result: str):
    results = {}
    if os.path.exists(RESULTS_JSON):
        try:
            with open(RESULTS_JSON, "r", encoding="utf-8") as f:
                results = json.load(f)
        except:
            pass

    # DO NOT overwrite a transfer
    if results.get(phone, {}).get("result") == "successfully_transferred":
        return

    results[phone] = {
        "name": name,
        "phone": phone,
        "result": result,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    with open(RESULTS_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)


def generate_final_output_csv():
    if not os.path.exists(CONTACTS_CSV):
        print("No contacts.csv found")
        return

    results = {}
    if os.path.exists(RESULTS_JSON):
        try:
            with open(RESULTS_JSON, "r", encoding="utf-8") as f:
                results = json.load(f)
        except:
            pass

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(OUTPUT_CSV_DIR, f"call_results_{ts}.csv")

    with open(CONTACTS_CSV, newline='', encoding='utf-8') as fin:
        reader = csv.DictReader(fin)
        fieldnames = reader.fieldnames or ["Client", "Name", "Phone"]
        if "Response" not in fieldnames:
            fieldnames = fieldnames + ["Response"]

        rows = []
        for row in reader:
            ph = normalize_phone(row.get("Phone", ""))
            resp = results.get(ph, {}).get("result", "")
            new_row = row.copy()
            new_row["Response"] = resp
            rows.append(new_row)

    with open(out_path, "w", newline='', encoding='utf-8') as fout:
        writer = csv.DictWriter(fout, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Output CSV created: {out_path}")

# Endpoints
@app.post("/upload-contacts")
async def upload_contacts(file: UploadFile):
    content = (await file.read()).decode('utf-8').splitlines()
    reader = csv.DictReader(content)

    required = {"Client", "Name", "Phone"}
    if not required.issubset(reader.fieldnames or []):
        return {"error": f"Missing columns: {required - set(reader.fieldnames or [])}"}

    with open(CONTACTS_CSV, "w", newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=reader.fieldnames)
        writer.writeheader()
        for row in reader:
            writer.writerow({k: (v or "").strip() for k, v in row.items()})

    if os.path.exists(RESULTS_JSON):
        os.remove(RESULTS_JSON)

    count = load_contacts_to_memory()

    with call_tracker["lock"]:
        call_tracker.update({"total": 0, "completed": 0, "running": False})

    return {"message": "Contacts uploaded", "count": count}

@app.post("/start-calls")
def start_calls(background_tasks: BackgroundTasks):
    global stop_requested
    stop_requested = False

    with call_tracker["lock"]:
        if call_tracker["running"]:
            return {"error": "Already running"}
        if not os.path.exists(CONTACTS_CSV):
            return {"error": "Upload contacts first"}

        count = load_contacts_to_memory()
        if count == 0:
            return {"error": "No contacts"}

        call_tracker["total"] = count
        call_tracker["completed"] = 0
        call_tracker["running"] = True

    background_tasks.add_task(run_outbound_calls)
    return {"status": "started", "total": count}

def run_outbound_calls():
    try:
        while not call_queue.empty():
            call_queue.get()

        with open(CONTACTS_CSV, newline='', encoding='utf-8') as f:
            if stop_requested:
                return

            reader = csv.DictReader(f)
            for row in reader:
                phone = normalize_phone(row.get("Phone", ""))
                name = row.get("Name", "").strip() or "there"
                client = row.get("Client", "").strip()

                if phone and client:
                    # Generate hello audio per PHONE (not client)
                    hello_path = os.path.join(AUDIO_DIR, f"hello_{phone}_v3.mp3")

                    if not os.path.exists(hello_path):
                        hello_text = f"Hello {name},"
                        generate_audio(hello_text, hello_path)

                    call_queue.put((phone, name, client))

        start_next_call()

    finally:
        with call_tracker["lock"]:
            call_tracker["running"] = False


@app.post("/stop-calls")
def stop_calls():
    global stop_requested

    stop_requested = True

    with call_tracker["lock"]:
        call_tracker["running"] = False

    return {"status": "stopped"}



@app.api_route("/twilio/voice", methods=["GET", "POST"])
async def twilio_voice(request: Request):
    client = request.query_params.get("client")

    phone = None
    for p, c in contact_map.items():
        if c["client"] == client:
            phone = p
            break

    vr = VoiceResponse()

    if not phone:
        vr.say("System error. Goodbye.")
        return Response(str(vr), media_type="application/xml")

    # 1) Say name first
    vr.play(f"{BASE_URL}/audio/hello_{phone}_v3.mp3")

    # 2) Play full script (no gather here)
    vr.play(f"{BASE_URL}/audio/common_message_v3.mp3")

    # 3) NOW gather — Twilio will pass speech said earlier too
    gather = Gather(
        input="speech dtmf",
        speech_timeout="auto",
        timeout=6,
        num_digits=1,
        action=f"/twilio/transfer?phone={phone}",
        method="POST"
    )

    vr.append(gather)

    # 4) If nothing was said at all
    vr.play(f"{BASE_URL}/audio/thank_you_goodbye_v3.mp3")

    return Response(str(vr), media_type="application/xml")



@app.post("/twilio/transfer")
async def transfer_call(request: Request):
    form = await request.form()

    phone_raw = request.query_params.get("phone")  # ✅ ORIGINAL CUSTOMER
    phone = normalize_phone(phone_raw)

    digits = form.get("Digits")
    speech = (form.get("SpeechResult") or "").lower()

    contact = contact_map.get(phone)
    name = contact["name"] if contact else "customer"

    wants_transfer = (
        digits == "1" or
        any(w in speech for w in [
            "transfer", "agent", "human", "person", "yes",
            "operator", "representative", "connect"
        ])
    )

    vr = VoiceResponse()

    if wants_transfer:
        save_result(phone, name, "successfully_transferred")
        vr.play(f"{BASE_URL}/audio/please_hold_v3.mp3") 
        vr.dial(HUMAN_AGENT_NUMBER)
    else:
        vr.play(f"{BASE_URL}/audio/thank_you_goodbye_v3.mp3") 

    return Response(str(vr), media_type="application/xml")



@app.post("/twilio/status")
async def call_status(request: Request):
    form = await request.form()

    phone_raw = form.get("To") or form.get("Called") or form.get("From")
    phone = normalize_phone(phone_raw)

    status = form.get("CallStatus")
    duration = int(form.get("CallDuration") or 0)

    print(f"STATUS → {phone_raw} → {phone} | {status} | {duration}s")

    contact = contact_map.get(phone)
    if not contact:
        print(f"[WARN] No contact found for {phone_raw}")
        return "ok"

    name = contact["name"]

    # ── check if already transferred ──
    already_transferred = False
    if os.path.exists(RESULTS_JSON):
        try:
            with open(RESULTS_JSON, "r", encoding="utf-8") as f:
                results = json.load(f)
                if results.get(phone, {}).get("result") == "successfully_transferred":
                    print("Already transferred, skip overwrite")
                    already_transferred = True
        except:
            pass

    # ── save result only if not transferred ──
    if not already_transferred:
        if status == "no-answer":
            save_result(phone, name, "no_answer")
        elif status == "busy":
            save_result(phone, name, "busy")
        elif status in ["failed", "canceled"]:
            save_result(phone, name, status)
        elif status == "completed":
            save_result(phone, name, "answered_no_transfer")

    # ── ALWAYS count & continue ──
    with call_tracker["lock"]:
        call_tracker["completed"] += 1
        done = call_tracker["completed"]
        total = call_tracker["total"]
        print(f"Progress: {done}/{total}")

        if done >= total and total > 0:
            print("All calls finished → generating output CSV")
            generate_final_output_csv()
            # call_tracker.update(total=0, completed=0, running=False)
            call_tracker["running"] = False

    start_next_call()
    return "ok"

@app.get("/result-csv")
def result_csv():
    if not os.path.exists(OUTPUT_CSV_DIR):
        return {"status": "processing"}

    files = [
        f for f in os.listdir(OUTPUT_CSV_DIR)
        if f.endswith(".csv")
    ]

    if not files:
        return {"status": "processing"}

    # latest generated CSV
    latest_file = max(
        files,
        key=lambda f: os.path.getctime(os.path.join(OUTPUT_CSV_DIR, f))
    )

    file_path = os.path.join(OUTPUT_CSV_DIR, latest_file)

    return FileResponse(
        file_path,
        media_type="text/csv",
        filename=latest_file
    )


@app.get("/call-progress")
def call_progress():
    with call_tracker["lock"]:
        return {
            "total": call_tracker["total"],
            "completed": call_tracker["completed"]
        }
