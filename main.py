from fastapi import FastAPI, UploadFile, Request, BackgroundTasks, Depends, HTTPException, status, Form
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
from fastapi.responses import JSONResponse
from fastapi.responses import RedirectResponse

from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta
from fastapi.security import OAuth2PasswordBearer
from fastapi.responses import HTMLResponse

from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import bcrypt


from config import HUMAN_AGENT_NUMBER, COMMON_MESSAGE_TEXT

from config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_PHONE_NUMBER,
    BASE_URL,
    ELEVENLABS_API_KEY,
    VOICE_ID,
    SECRET_KEY,
    ALGORITHM,
    ACCESS_TOKEN_EXPIRE_MINUTES
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



# ─── Paths ──────────────
CONTACTS_CSV     = "contacts.csv"
RESULTS_JSON     = "call_results.json"
OUTPUT_CSV_DIR   = "output_results"
AUDIO_DIR        = "audio"

os.makedirs(OUTPUT_CSV_DIR, exist_ok=True)
os.makedirs(AUDIO_DIR, exist_ok=True)
app.mount("/audio", StaticFiles(directory=AUDIO_DIR), name="audio")

# ─── ElevenLabs TTS ────
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
            # url=f"{BASE_URL}/twilio/voice?client={client_id}",
            url=f"{BASE_URL}/twilio/voice?phone={phone}",
            status_callback=f"{BASE_URL}/twilio/status",
            # status_callback_event=["completed"],
            status_callback_event=["initiated", "ringing", "answered", "completed"],
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
# @app.get("/")
# def serve_home():
#     return FileResponse("index.html")

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
    # client = request.query_params.get("client")

    # phone = None
    # for p, c in contact_map.items():
    #     if c["client"] == client:
    #         phone = p
    #         break

    phone = normalize_phone(request.query_params.get("phone"))

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

    phone_raw = request.query_params.get("phone")
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




# --- SQLite Setup ---
SQLALCHEMY_DATABASE_URL = "sqlite:///./users.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# User Model
class UserDB(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)

# Create the database file
Base.metadata.create_all(bind=engine)

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()



@app.on_event("startup")
async def startup_event():
    db = SessionLocal()
    user = db.query(UserDB).filter(UserDB.username == "admin").first()
    if not user:
        # Change this line:
        hashed = hash_password("admin123") 
        new_user = UserDB(username="admin", hashed_password=hashed)
        db.add(new_user)
        db.commit()
    db.close()

def hash_password(password: str) -> str:
    # Generate a salt and hash the password
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    # Check if the provided password matches the stored hash
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

# Custom dependency to get user from Cookie
# This handles API security
async def get_current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("access_token")
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    
    try:
        # 1. Verify the signature and expiration using your SECRET_KEY
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
            
    except JWTError:
        # This triggers if the token is fabricated, expired, or tampered with
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials")

    # 2. Double check the database to ensure the user still exists
    user = db.query(UserDB).filter(UserDB.username == username).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists")
        
    return username


# Route to serve the Login Page
@app.get("/login", response_class=HTMLResponse)
async def get_login():
    return FileResponse("login.html")

# Route to serve the Dashboard (index.html)
@app.get("/index.html", response_class=HTMLResponse)
async def get_dashboard(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("access_token")
    
    if not token:
        return RedirectResponse(url="/login")

    try:
        # Verify the token is real
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        user = db.query(UserDB).filter(UserDB.username == username).first()
        
        if not user:
            return RedirectResponse(url="/login")
            
        # If we reach here, the token is 100% valid and verified
        return FileResponse("index.html")
        
    except JWTError:
        # Token was fabricated or expired! Clear it and send back to login
        response = RedirectResponse(url="/login")
        response.delete_cookie("access_token")
        return response

# Route to redirect the root (/) to the index page
@app.get("/", response_class=HTMLResponse)
async def root():
    return RedirectResponse(url="/index.html")

# --- AUTH ENDPOINTS ---

@app.post("/token")
async def login(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.username == username).first()
    
    # Verify user exists and password hash matches
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    
    access_token = jwt.encode(
        {"sub": username, "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)},
        SECRET_KEY, algorithm=ALGORITHM
    )
    
    response = JSONResponse(content={"message": "Logged in"})
    response.set_cookie(
        key="access_token", 
        value=access_token, 
        httponly=True, 
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax"
    )
    return response


@app.post("/update-account")
async def update_account(
    current_password: str = Form(...), 
    new_username: str = Form(None),
    new_password: str = Form(None),
    current_user: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user = db.query(UserDB).filter(UserDB.username == current_user).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 1. ALWAYS verify the current password before making any changes
    if not verify_password(current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password incorrect")

    # 2. Handle Username Update
    if new_username and new_username != user.username:
        # Check if the new username is already taken by someone else
        existing_user = db.query(UserDB).filter(UserDB.username == new_username).first()
        if existing_user:
            raise HTTPException(status_code=400, detail="Username already taken")
        user.username = new_username

    # 3. Handle Password Update
    if new_password:
        user.hashed_password = hash_password(new_password)

    db.commit()
    return {"message": "Account updated successfully"}

@app.post("/logout")
async def logout():
    response = JSONResponse(content={"message": "Logged out"})
    response.delete_cookie("access_token")
    return response
