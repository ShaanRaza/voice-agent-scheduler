import os
import json
import re
import sys
import time
import datetime
import threading
import requests
from flask import Flask, jsonify, request, send_from_directory

# Google API Imports
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    google_libs_available = True
except ImportError:
    google_libs_available = False

app = Flask(__name__)

# File paths for storage
DATA_DIR = os.environ.get("DATA_DIR", ".")
if DATA_DIR != "." and not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR, exist_ok=True)

CALENDAR_FILE = os.path.join(DATA_DIR, "calendar_store.json")
LOGS_FILE = os.path.join(DATA_DIR, "logs_store.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
CONTACTS_FILE = os.path.join(DATA_DIR, "contacts_store.json")

# Public URL where this app is reachable (used as Vapi webhook target).
# Set PUBLIC_URL in your Render environment. Falls back to RENDER_EXTERNAL_URL
# (auto-set by Render) and finally to the Vapi webhook path on localhost.
PUBLIC_URL = (
    os.environ.get("PUBLIC_URL")
    or os.environ.get("RENDER_EXTERNAL_URL")
    or "http://localhost:" + os.environ.get("PORT", "8080")
).rstrip("/")

# ==========================================
# Persistent Storage Handlers
# ==========================================

def init_config():
    if not os.path.exists(CONFIG_FILE):
        default_config = {
            "vapi_private_key": "",
            "vapi_public_key": "",
            "phone_number": "",
            "google_calendar_id": "",
            "google_oauth_client_id": "",
            "google_oauth_client_secret": "",
            "assistant_id": ""
        }
        with open(CONFIG_FILE, "w") as f:
            json.dump(default_config, f, indent=2)

def get_config():
    init_config()
    with open(CONFIG_FILE, "r") as f:
        config = json.load(f)
        if "google_calendar_id" not in config:
            config["google_calendar_id"] = ""
    # Env var override for non-sensitive settings (e.g. GOOGLE_CALENDAR_ID).
    env_overrides = {
        "google_calendar_id": os.environ.get("GOOGLE_CALENDAR_ID", "").strip(),
        "phone_number": os.environ.get("PHONE_NUMBER", "").strip(),
        "smtp_email": os.environ.get("SMTP_EMAIL", "").strip(),
    }
    for k, v in env_overrides.items():
        if v:
            config[k] = v
    # Merge in sensitive values from env/memory (never persisted to config.json).
    for key in RUNTIME_SECRETS:
        val = get_secret(key)
        if val:
            config[key] = val
    return config

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

def init_calendar(force=False):
    if os.path.exists(CALENDAR_FILE) and not force:
        return
    
    # Generate slots for the next 7 days, starting today in IST
    slots = []
    ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    now_ist = datetime.datetime.now(ist_tz)
    start_date = now_ist.date()
    
    # Typical time slots
    times = ["09:00 AM", "10:00 AM", "11:00 AM", "01:00 PM", "02:00 PM", "03:00 PM", "04:00 PM"]
    
    for i in range(7):
        day = start_date + datetime.timedelta(days=i)
        # Skip Sundays
        if day.weekday() == 6:  # 6 is Sunday
            continue
            
        date_str = day.strftime("%Y-%m-%d")
        day_name = day.strftime("%A")
        
        for t in times:
            slot_id = f"{date_str}_{t.replace(' ', '')}"
            slots.append({
                "id": slot_id,
                "date": date_str,
                "day": day_name,
                "time": t,
                "status": "available",
                "booked_by": None
            })
    
    with open(CALENDAR_FILE, "w") as f:
        json.dump(slots, f, indent=2)
    print(f"Initialized calendar with {len(slots)} slots.")

def ensure_future_slots(slots):
    ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    now_ist = datetime.datetime.now(ist_tz)
    today = now_ist.date()
    
    # Typical time slots
    times = ["09:00 AM", "10:00 AM", "11:00 AM", "01:00 PM", "02:00 PM", "03:00 PM", "04:00 PM"]
    
    existing_dates = {s["date"] for s in slots}
    modified = False
    
    for i in range(7):
        day = today + datetime.timedelta(days=i)
        # Skip Sundays
        if day.weekday() == 6:  # 6 is Sunday
            continue
            
        date_str = day.strftime("%Y-%m-%d")
        if date_str not in existing_dates:
            day_name = day.strftime("%A")
            for t in times:
                slot_id = f"{date_str}_{t.replace(' ', '')}"
                slots.append({
                    "id": slot_id,
                    "date": date_str,
                    "day": day_name,
                    "time": t,
                    "status": "available",
                    "booked_by": None
                })
            modified = True
            
    if modified:
        def get_sort_key(s):
            dt = parse_slot_time(s["date"], s["time"])
            return dt.timestamp() if dt else 0
        slots.sort(key=get_sort_key)
        save_calendar(slots)

def get_calendar():
    if not os.path.exists(CALENDAR_FILE):
        init_calendar()
    with open(CALENDAR_FILE, "r") as f:
        slots = json.load(f)
        
    ensure_future_slots(slots)
        
    ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    now_ist = datetime.datetime.now(ist_tz)
        
    # Sync visual database dynamically if Google Calendar is configured
    config = get_config()
    calendar_id = config.get("google_calendar_id")
    service = get_calendar_service()
    
    google_events = []
    if service and calendar_id:
        google_events = get_google_calendar_events(service, calendar_id)
        
    for s in slots:
        # Check if the slot is in the past
        slot_dt = parse_slot_time(s["date"], s["time"])
        if slot_dt and slot_dt < now_ist:
            s["status"] = "past"
            continue
            
        if s["status"] == "available":
            if google_events and is_slot_blocked_by_google(s, google_events):
                s["status"] = "booked"
                s["booked_by"] = {
                    "name": "Google Calendar Conflict",
                    "contact": "External Meeting",
                    "booked_at": datetime.datetime.now().isoformat()
                }
    return slots

def save_calendar(calendar):
    with open(CALENDAR_FILE, "w") as f:
        json.dump(calendar, f, indent=2)

def init_logs():
    if not os.path.exists(LOGS_FILE):
        with open(LOGS_FILE, "w") as f:
            json.dump([], f)

def clean_logs_spelling(logs):
    contacts = get_contacts()
    # Create mapping from call_id to email
    call_email_map = {}
    for c in contacts:
        cid = c.get("call_id")
        email = c.get("email")
        if cid and email:
            call_email_map[cid] = email
            
    email_spelled_pattern = re.compile(
        r'\b[a-z0-9\s_\"\'\-\(\)]*(?:@|at\s+the\s+rate\s+of|at\s+the\s+rate|at\s+rate|at)\s*[a-z0-9\s_\"\'\-\(\)]*(?:\.|dot)\s*(?:com|c\s+o\s+m|net|org|edu)\b',
        re.IGNORECASE
    )
    
    prefixes_to_strip = [
        r"^so\s+that\s+is\s+",
        r"^my\s+email\s+is\s+",
        r"^please\s+send\s+it\s+to\s+",
        r"^is\s+it\s+",
        r"^it\s+is\s+",
        r"^address\s+is\s+",
        r"^email\s+is\s+",
        r"^is\s+"
    ]
    
    modified = False
    for log in logs:
        cid = log.get("call_id")
        correct_email = call_email_map.get(cid)
        if not correct_email:
            continue
            
        transcript = log.get("transcript", [])
        for msg in transcript:
            text = msg.get("text", "")
            if not text:
                continue
                
            match = email_spelled_pattern.search(text)
            if match:
                matched_str = match.group(0)
                cleaned_match = matched_str
                for prefix in prefixes_to_strip:
                    cleaned_match = re.sub(prefix, "", cleaned_match, flags=re.IGNORECASE)
                
                new_text = text.replace(matched_str, matched_str.replace(cleaned_match, correct_email))
                if new_text != text:
                    msg["text"] = new_text
                    modified = True
                    
    return logs, modified

def get_logs():
    init_logs()
    with open(LOGS_FILE, "r") as f:
        try:
            logs = json.load(f)
        except Exception:
            logs = []
            
    try:
        cleaned_logs, modified = clean_logs_spelling(logs)
        if modified:
            save_logs(cleaned_logs)
        return cleaned_logs
    except Exception as e:
        print(f"Error cleaning logs spelling: {e}")
        return logs

def save_logs(logs):
    with open(LOGS_FILE, "w") as f:
        json.dump(logs, f, indent=2)

# ==========================================
# Contacts & Leads Persistent Database
# ==========================================

def init_contacts():
    if not os.path.exists(CONTACTS_FILE):
        with open(CONTACTS_FILE, "w") as f:
            json.dump([], f)

def get_contacts():
    init_contacts()
    with open(CONTACTS_FILE, "r") as f:
        try:
            contacts = json.load(f)
        except Exception:
            contacts = []
            
    # Schema migration/upgrade step
    migrated = False
    for c in contacts:
        if "id" not in c:
            import uuid
            c["id"] = str(uuid.uuid4())
            migrated = True
        if "notes" not in c:
            c["notes"] = ""
            migrated = True
        if "status" not in c:
            c["status"] = "Scheduled"
            migrated = True
        if "sentiment" not in c:
            c["sentiment"] = "Neutral"
            migrated = True
        if "summary" not in c:
            c["summary"] = "No summary available for this call yet."
            migrated = True
        if "prep_sheet" not in c:
            c["prep_sheet"] = ["Waiting for post-call intelligence report to compile key recruiter highlights."]
            migrated = True
        if "recording_url" not in c:
            c["recording_url"] = ""
            migrated = True
            
    if migrated:
        save_contacts(contacts)
        
    return contacts

def save_contacts(contacts):
    with open(CONTACTS_FILE, "w") as f:
        json.dump(contacts, f, indent=2)

def add_contact(name, email, phone, date_str, time_str, event_link="", meet_link="", call_id=None, google_event_id=""):
    import uuid
    contacts = get_contacts()
    new_id = str(uuid.uuid4())
    contacts.append({
        "id": new_id,
        "name": name,
        "email": email,
        "phone": phone,
        "date": date_str,
        "time": time_str,
        "google_event_link": event_link,
        "google_meet_link": meet_link,
        "google_event_id": google_event_id,
        "call_id": call_id,
        "status": "Scheduled",
        "notes": "",
        "sentiment": "Neutral",
        "summary": "No summary available for this call yet.",
        "prep_sheet": [
            "Waiting for post-call intelligence report to compile key recruiter highlights."
        ],
        "recording_url": "",
        "created_at": datetime.datetime.now().isoformat()
    })
    save_contacts(contacts)
    return new_id

def update_call_status(call_id, status):
    logs = get_logs()
    
    # Find existing call
    call_record = None
    for log in logs:
        if log.get("call_id") == call_id:
            call_record = log
            break
            
    if not call_record:
        call_record = {
            "call_id": call_id,
            "status": status,
            "timestamp": datetime.datetime.now().isoformat(),
            "transcript": []
        }
        logs.append(call_record)
    else:
        call_record["status"] = status
        
    save_logs(logs)
    print(f"[Call {call_id}] Status updated to: {status}")

def sanitize_spelling(text):
    if not text:
        return text
    # Replace name misspellings
    text = re.sub(r'\b(Sean|Shaun)\b', 'Shaan', text)
    text = re.sub(r'\b(sean|shaun)\b', 'shaan', text)
    text = re.sub(r'\b(Rosa|dazar|Dazar)\b', 'Raza', text)
    text = re.sub(r'\b(rosa|dazar)\b', 'raza', text)
    return text

def normalize_email(email_str):
    if not email_str:
        return ""
    
    # Lowercase the entire string
    email = email_str.lower().strip()
    
    # Replace common words for symbols with word boundaries
    email = re.sub(r'\bat\s*(?:the\s*)?rate\s*(?:of)?\b', '@', email)
    email = re.sub(r'\b(at|@)\b', '@', email)
    email = re.sub(r'\b(dot|\.)\b', '.', email)
    email = re.sub(r'\b(underscore)\b', '_', email)
    email = re.sub(r'\b(dash|hyphen)\b', '-', email)
    
    # Replace compound number words (e.g. "ninety nine" -> "99")
    compounds = {
        "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
        "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90
    }
    units = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9
    }
    
    for c_word, c_val in compounds.items():
        for u_word, u_val in units.items():
            email = re.sub(rf'\b{c_word}\s+{u_word}\b', str(c_val + u_val), email)
            
    # Standalone double digits and teens
    teens = {
        "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
        "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19
    }
    for word, val in teens.items():
        email = re.sub(rf'\b{word}\b', str(val), email)
        
    for word, val in compounds.items():
        email = re.sub(rf'\b{word}\b', str(val), email)
        
    for word, val in units.items():
        email = re.sub(rf'\b{word}\b', str(val), email)
        
    # Standalone zero
    email = re.sub(r'\bzero\b', '0', email)
    
    # Replace spelling of common domains
    email = re.sub(r'\bg\s*male\b', 'gmail', email)
    email = re.sub(r'\bg\s*mail\b', 'gmail', email)
    email = re.sub(r'\bhot\s*male\b', 'hotmail', email)
    email = re.sub(r'\bhot\s*mail\b', 'hotmail', email)
    
    # Remove all remaining whitespace
    email = re.sub(r'\s+', '', email)
    
    return email

def normalize_phone(phone_str):
    if not phone_str:
        return ""
    p = phone_str.lower().strip()
    if p in ["na", "n/a", "none", "no phone", "no"]:
        return "NA"
        
    compounds = {
        "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
        "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90
    }
    units = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9
    }
    
    for c_word, c_val in compounds.items():
        for u_word, u_val in units.items():
            p = re.sub(rf'\b{c_word}\s+{u_word}\b', str(c_val + u_val), p)
            
    teens = {
        "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
        "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19
    }
    for word, val in teens.items():
        p = re.sub(rf'\b{word}\b', str(val), p)
        
    for word, val in compounds.items():
        p = re.sub(rf'\b{word}\b', str(val), p)
        
    for word, val in units.items():
        p = re.sub(rf'\b{word}\b', str(val), p)
        
    p = re.sub(r'\bzero\b', '0', p)
        
    # Keep only digits and '+'
    p = re.sub(r'[^0-9+]', '', p)
    return p


def add_log_message(call_id, role, text):
    text = sanitize_spelling(text)
    logs = get_logs()
    
    call_record = None
    for log in logs:
        if log.get("call_id") == call_id:
            call_record = log
            break
            
    if not call_record:
        call_record = {
            "call_id": call_id,
            "status": "in-progress",
            "timestamp": datetime.datetime.now().isoformat(),
            "transcript": []
        }
        logs.append(call_record)
        
    # Prevent duplicate text segments sent by speech-updates
    # We can check if the last message by the same role is identical or a prefix
    transcript = call_record["transcript"]
    if transcript and transcript[-1]["role"] == role:
        # If the text has updated (longer), update the last message
        # Voice agent transcripts can arrive incrementally
        if text.startswith(transcript[-1]["text"]):
            transcript[-1]["text"] = text
            transcript[-1]["timestamp"] = datetime.datetime.now().isoformat()
        elif not transcript[-1]["text"].startswith(text):
            transcript.append({
                "role": role,
                "text": text,
                "timestamp": datetime.datetime.now().isoformat()
            })
    else:
        transcript.append({
            "role": role,
            "text": text,
            "timestamp": datetime.datetime.now().isoformat()
        })
        
    save_logs(logs)

# ==========================================
# Google Calendar Sync Helpers
# ==========================================

def get_calendar_service():
    scopes = ['https://www.googleapis.com/auth/calendar']

    # 1. Try user OAuth token (in-memory / env var — never on disk)
    oauth_json = get_secret("oauth_token_json")
    if oauth_json:
        try:
            from google.oauth2.credentials import Credentials as UserCredentials
            from google.auth.transport.requests import Request

            info = json.loads(oauth_json)
            # Quick sanity check: required fields for the Google auth library
            for required in ("client_id", "client_secret", "refresh_token"):
                if not info.get(required):
                    raise ValueError(f"OAuth token is missing required field '{required}'. Re-do the Google Account connect flow and copy the fresh token to Render's OAUTH_TOKEN_JSON env var.")
            creds = UserCredentials.from_authorized_user_info(info, scopes=scopes)
            if creds.expired and creds.refresh_token:
                print("Refreshing Google OAuth2 user access token...")
                creds.refresh(Request())
                info["token"] = creds.token
                set_secret("oauth_token_json", json.dumps(info))
                print("Refreshed token kept in memory only.")

            if creds.valid:
                return build('calendar', 'v3', credentials=creds)
        except Exception as e:
            print(f"Error initializing Google Calendar client with user OAuth2: {e}")
            print("  → Falling back to service account if GOOGLE_CREDENTIALS_JSON is set.")

    # 2. Fall back to service account (in-memory / env var — never on disk)
    creds_json = get_secret("google_credentials_json")
    if creds_json:
        try:
            from google.oauth2 import service_account as sa
            info = json.loads(creds_json)
            sa_email = info.get("client_email", "(unknown)")
            creds = sa.Credentials.from_service_account_info(info, scopes=scopes)
            print(f"[google] Using service account: {sa_email}")
            return build('calendar', 'v3', credentials=creds)
        except Exception as e:
            print(f"Error initializing Google Calendar client with service account: {e}")

    return None

def get_google_calendar_events(service, calendar_id):
    if not service or not calendar_id:
        return []
    try:
        # Fetch events for the next 10 days
        now = datetime.datetime.now(datetime.timezone.utc)
        time_min = now.isoformat()
        time_max = (now + datetime.timedelta(days=10)).isoformat()
        
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        return events_result.get('items', [])
    except Exception as e:
        print(f"Error fetching Google Calendar events: {e}")
        return []

def parse_slot_time(date_str, time_str):
    try:
        # Combine e.g. "2026-06-08" and "10:00 AM"
        dt_str = f"{date_str} {time_str}"
        naive_dt = datetime.datetime.strptime(dt_str, "%Y-%m-%d %I:%M %p")
        # Assume Indian Standard Time (+05:30)
        ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        return naive_dt.replace(tzinfo=ist_tz)
    except Exception as e:
        print(f"Error parsing slot datetime ({date_str} {time_str}): {e}")
        return None

def is_slot_blocked_by_google(slot, google_events):
    slot_start = parse_slot_time(slot["date"], slot["time"])
    if not slot_start:
        return False
    slot_end = slot_start + datetime.timedelta(hours=1)
    
    for event in google_events:
        if event.get('status') == 'cancelled':
            continue
            
        start_data = event.get('start', {})
        end_data = event.get('end', {})
        
        # Check all-day event
        if 'date' in start_data:
            if slot["date"] == start_data['date']:
                return True
                
        # Check timed event
        elif 'dateTime' in start_data:
            try:
                event_start = datetime.datetime.fromisoformat(start_data['dateTime'])
                event_end = datetime.datetime.fromisoformat(end_data['dateTime'])
                if event_start < slot_end and event_end > slot_start:
                    return True
            except Exception as e:
                pass
    return False

def create_google_calendar_event(service, calendar_id, candidate_name, candidate_email, candidate_phone, date_str, time_str):
    if not service or not calendar_id:
        return None, None
    try:
        slot_start = parse_slot_time(date_str, time_str)
        if not slot_start:
            return None, None
        slot_end = slot_start + datetime.timedelta(hours=1)
        
        description_text = f"Interview booked by Shaan's AI Assistant.\nCandidate Name: {candidate_name}\nCandidate Email: {candidate_email}\nCandidate Phone: {candidate_phone}"
        
        event_body = {
            'summary': f'Interview: {candidate_name} x Shaan Raza',
            'description': description_text,
            'start': {
                'dateTime': slot_start.isoformat(),
                'timeZone': 'Asia/Kolkata',
            },
            'end': {
                'dateTime': slot_end.isoformat(),
                'timeZone': 'Asia/Kolkata',
            }
        }
        
        # Try inserting directly into Shaan's calendar, inviting recruiter, with Meet Link
        event_body_full = event_body.copy()
        event_body_full['conferenceData'] = {
            'createRequest': {
                'requestId': f"meet-{int(time.time())}",
                'conferenceSolutionKey': {
                    'type': 'hangoutsMeet'
                }
            }
        }
        if candidate_email and "@" in candidate_email:
            event_body_full['attendees'] = [{'email': candidate_email.strip()}]
            
        try:
            print(f"Attempting to write event to calendar {calendar_id} with recruiter attendee and conference link...")
            event = service.events().insert(
                calendarId=calendar_id,
                body=event_body_full,
                conferenceDataVersion=1,
                sendUpdates='all'
            ).execute()
            print("Successfully created calendar event with attendee and Meet link.")
        except Exception as api_err:
            print(f"Failed to create event with attendees/Meet (Error: {api_err}). Falling back to inserting event directly on Shaan's calendar without attendees or Meet link...")
            event = service.events().insert(
                calendarId=calendar_id,
                body=event_body
            ).execute()
            print("Successfully created calendar event on Shaan's calendar without attendees.")
            
        html_link = event.get('htmlLink')
        meet_link = ""
        if 'conferenceData' in event:
            for entry in event['conferenceData'].get('entryPoints', []):
                if entry.get('entryPointType') == 'video':
                    meet_link = entry.get('uri')
                    break
                    
        return html_link, meet_link
    except Exception as e:
        print(f"Error creating Google Calendar event: {e}")
        return None, None

# ==========================================
# Scheduling Logic (Agent Custom Tools)
# ==========================================

def handle_check_calendar(date_str=None):
    slots = get_calendar()
    print(f"Tool Call: check_calendar_availability (date={date_str})")
    
    if date_str:
        # Standardise date check
        available = [s for s in slots if s["date"] == date_str.strip() and s["status"] == "available"]
        if not available:
            return f"I'm sorry, but there are no available interview slots on {date_str}. Please ask about another day."
        
        slot_list = ", ".join([s["time"] for s in available])
        return f"On {date_str}, I am available at: {slot_list}."
    else:
        # General availability check: group available slots for the next 3 days they occur
        available = [s for s in slots if s["status"] == "available"]
        if not available:
            return "All interview slots are currently booked. Please ask candidate to contact support."
            
        grouped = {}
        for s in available:
            grouped.setdefault(s["date"], []).append(s["time"])
            
        # Select first 3 days with availability
        sorted_dates = sorted(grouped.keys())[:3]
        result_parts = []
        for d in sorted_dates:
            times_str = ", ".join(grouped[d][:4]) # Show up to 4 slots per day
            # Format day name nicely
            day_name = next(s["day"] for s in available if s["date"] == d)
            result_parts.append(f"{day_name}, {d} at {times_str}")
            
        return "Here are my next available slots:\n" + "\n".join(result_parts) + "\nWhich of these works for you?"

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def send_booking_email(recipient_email, recipient_name, date_str, time_str):
    config = get_config()
    smtp_email = config.get("smtp_email")
    smtp_password = config.get("smtp_password")
    
    if not smtp_email or not smtp_password:
        print("SMTP credentials not configured. Skipping email notification.")
        return False
        
    try:
        msg = MIMEMultipart()
        msg['From'] = smtp_email
        msg['To'] = recipient_email
        msg['Subject'] = f"Interview Confirmed: Shaan Raza x {recipient_name}"
        
        body = f"""Hi {recipient_name},

Your interview with Shaan Raza has been successfully booked.

Details:
- Date: {date_str}
- Time: {time_str}

Your interview has been booked. We look forward to speaking with you!

Best regards,
Shaan's AI Assistant
"""
        msg.attach(MIMEText(body, 'plain'))
        
        # Connect to Gmail SMTP server
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(smtp_email, smtp_password)
        server.sendmail(smtp_email, recipient_email, msg.as_string())
        server.quit()
        
        print(f"Successfully sent booking confirmation email to {recipient_email}")
        return True
    except Exception as e:
        print(f"Error sending booking confirmation email: {e}")
        return False

def handle_book_slot(interviewer_name, date_str, time_str, interviewer_email=None, interviewer_phone=None, candidate_contact=None, call_id=None):
    email = normalize_email(interviewer_email)
    phone = normalize_phone(interviewer_phone)
    
    if candidate_contact and not email and not phone:
        if "@" in candidate_contact or " at " in candidate_contact or " dot " in candidate_contact:
            email = normalize_email(candidate_contact)
        else:
            phone = normalize_phone(candidate_contact)
            
    print(f"Tool Call: book_interview_slot (name={interviewer_name}, email={email}, phone={phone}, date={date_str}, time={time_str}, call_id={call_id})")
    
    slots = get_calendar()
    clean_date = date_str.strip()
    clean_time = time_str.strip().upper()
    
    # Try fuzzy time normalization (e.g., "10:00 AM" vs "10 AM")
    normalized_req = clean_time.replace(" ", "")
    # Check if request is e.g. "10AM" -> convert to "10:00 AM" to match calendar
    match = re.match(r"^(\d+)(AM|PM)$", normalized_req)
    if match:
        hr = int(match.group(1))
        meridiem = match.group(2)
        normalized_req = f"{hr:02d}:00{meridiem}"
        
    matched_slot = None
    for s in slots:
        if s["date"] == clean_date:
            slot_time_norm = s["time"].upper().replace(" ", "")
            if slot_time_norm == normalized_req:
                matched_slot = s
                break
                
    # If no exact slot match, let's search for an approximate match on that date
    if not matched_slot:
        for s in slots:
            if s["date"] == clean_date and s["status"] == "available":
                # Check if the hour matches (e.g. "10:00 AM" matches "10 AM" or "10")
                slot_hr = s["time"].split(":")[0]
                req_hr = re.findall(r"\d+", clean_time)
                if req_hr and int(slot_hr) == int(req_hr[0]):
                    # Make sure AM/PM match
                    if ("PM" in clean_time and "PM" in s["time"]) or ("AM" in clean_time and "AM" in s["time"]) or ("PM" not in clean_time and "AM" not in clean_time):
                        matched_slot = s
                        break
                        
    if not matched_slot:
        return f"Error: No slot found on {date_str} matching {time_str}. Please double-check my available times."
        
    if matched_slot["status"] == "booked":
        return f"Error: The slot on {date_str} at {matched_slot['time']} is already booked. Please choose another slot."
        
    # Check if the slot is in the past
    slot_dt = parse_slot_time(clean_date, matched_slot["time"])
    ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    now_ist = datetime.datetime.now(ist_tz)
    if slot_dt and slot_dt < now_ist:
        return f"Error: The slot on {date_str} at {matched_slot['time']} has already passed. Please choose a future slot."

    # Book the slot
    matched_slot["status"] = "booked"
    matched_slot["booked_by"] = {
        "name": interviewer_name,
        "email": email,
        "phone": phone,
        "call_id": call_id,
        "booked_at": datetime.datetime.now().isoformat()
    }
    
    # Generate Google Calendar Invite
    config = get_config()
    calendar_id = config.get("google_calendar_id")
    service = get_calendar_service()
    
    event_link = ""
    event_id = ""
    meet_link = ""
    invite_msg = ""
    send_smtp = True
    
    if service and calendar_id:
        # Create standard calendar event with attendees and conferenceData (Meet solution)
        try:
            slot_start = parse_slot_time(date_str, matched_slot["time"])
            if slot_start:
                slot_end = slot_start + datetime.timedelta(hours=1)
                description_text = f"Interview booked by Shaan's AI Assistant.\nCandidate Name: {interviewer_name}\nCandidate Email: {email}\nCandidate Phone: {phone}"
                
                event_body = {
                    'summary': f'Interview: {interviewer_name} x Shaan Raza',
                    'description': description_text,
                    'start': {
                        'dateTime': slot_start.isoformat(),
                        'timeZone': 'Asia/Kolkata',
                    },
                    'end': {
                        'dateTime': slot_end.isoformat(),
                        'timeZone': 'Asia/Kolkata',
                    },
                    'conferenceData': {
                        'createRequest': {
                            'requestId': f"meet-{int(time.time())}",
                            'conferenceSolutionKey': {
                                'type': 'hangoutsMeet'
                            }
                        }
                    }
                }
                
                if email and "@" in email:
                    event_body['attendees'] = [{'email': email.strip()}]
                    
                # Level 1: Full insert with attendees and Meet link (using OAuth2 user credentials)
                try:
                    print(f"[Calendar] Level 1: Inserting event on {calendar_id} with attendees and Meet link...")
                    event = service.events().insert(
                        calendarId=calendar_id,
                        body=event_body,
                        conferenceDataVersion=1,
                        sendUpdates='all'
                    ).execute()
                    event_link = event.get('htmlLink')
                    event_id = event.get('id') or ""
                    
                    if 'conferenceData' in event:
                        for entry in event['conferenceData'].get('entryPoints', []):
                            if entry.get('entryPointType') == 'video':
                                meet_link = entry.get('uri')
                                break
                                
                    if event_link:
                        matched_slot["booked_by"]["google_event_link"] = event_link
                        matched_slot["booked_by"]["google_event_id"] = event_id
                        if meet_link:
                            matched_slot["booked_by"]["google_meet_link"] = meet_link
                        invite_msg = " A Google Calendar invitation with a Google Meet link has been sent to your email."
                        send_smtp = False  # Natively sent by Google Calendar API!
                except Exception as e_level1:
                    print(f"[Calendar] Level 1 insert failed: {e_level1}. Falling back to Level 2...")
                    
                    # Level 2: Fallback without attendees (service account or domain restriction fallback)
                    try:
                        event_body_no_att = event_body.copy()
                        if 'attendees' in event_body_no_att:
                            del event_body_no_att['attendees']
                        event = service.events().insert(
                            calendarId=calendar_id,
                            body=event_body_no_att,
                            conferenceDataVersion=1
                        ).execute()
                        event_link = event.get('htmlLink')
                        event_id = event.get('id') or ""
                        
                        if 'conferenceData' in event:
                            for entry in event['conferenceData'].get('entryPoints', []):
                                if entry.get('entryPointType') == 'video':
                                    meet_link = entry.get('uri')
                                    break
                                    
                        if event_link:
                            matched_slot["booked_by"]["google_event_link"] = event_link
                            matched_slot["booked_by"]["google_event_id"] = event_id
                            if meet_link:
                                matched_slot["booked_by"]["google_meet_link"] = meet_link
                            invite_msg = " A Google Calendar invitation has been added to Shaan's calendar."
                            send_smtp = True  # Send SMTP backup email since attendees could not be invited on Google Calendar
                    except Exception as e_level2:
                        print(f"[Calendar] Level 2 insert failed: {e_level2}. Falling back to Level 3...")
                        
                        # Level 3: Fallback without attendees or Meet link (basic event only)
                        try:
                            event_body_basic = event_body.copy()
                            if 'attendees' in event_body_basic:
                                del event_body_basic['attendees']
                            if 'conferenceData' in event_body_basic:
                                del event_body_basic['conferenceData']
                            event = service.events().insert(
                                calendarId=calendar_id,
                                body=event_body_basic
                            ).execute()
                            event_link = event.get('htmlLink')
                            event_id = event.get('id') or ""
                            
                            if event_link:
                                matched_slot["booked_by"]["google_event_link"] = event_link
                                matched_slot["booked_by"]["google_event_id"] = event_id
                                invite_msg = " A Google Calendar invitation has been added to Shaan's calendar."
                                send_smtp = True  # Send SMTP backup email
                        except Exception as e_level3:
                            print(f"[Calendar] Level 3 insert failed: {e_level3}")
        except Exception as e:
            print(f"Error preparing Google Calendar event: {e}")
 
    # Send email notification via SMTP only if Google Calendar didn't handle it natively
    if email and send_smtp:
        t = threading.Thread(
            target=send_booking_email,
            args=(email, interviewer_name, date_str, matched_slot["time"])
        )
        t.daemon = True
        t.start()
 
    # Save contact to leads list
    add_contact(interviewer_name, email, phone, date_str, matched_slot["time"], event_link, meet_link, call_id, google_event_id=event_id)
    
    save_calendar(slots)
    return f"Success! Interview has been booked for {interviewer_name} on {date_str} at {matched_slot['time']}.{invite_msg}"

# ==========================================
# REST API Endpoints
# ==========================================

@app.route("/")
def serve_index():
    return send_from_directory("static", "index.html")

@app.route("/static/<path:path>")
def serve_static(path):
    return send_from_directory("static", path)

@app.route("/api/status")
def api_status():
    config = get_config()
    return jsonify({
        "public_url": PUBLIC_URL,
        "vapi_private_key_configured": secret_configured("vapi_private_key"),
        "vapi_public_key_configured": secret_configured("vapi_public_key"),
        "vapi_public_key": get_secret("vapi_public_key") or "",
        "assistant_id": config.get("assistant_id"),
        "phone_number": config.get("phone_number"),
        "google_calendar_id": config.get("google_calendar_id", ""),
        "smtp_email": config.get("smtp_email", ""),
        "smtp_password_configured": bool(config.get("smtp_password")),
        "google_oauth_client_id_configured": secret_configured("google_oauth_client_id"),
        "google_oauth_client_secret_configured": secret_configured("google_oauth_client_secret"),
        "google_credentials_configured": secret_configured("google_credentials_json"),
        "oauth_token_configured": secret_configured("oauth_token_json"),
        "is_deployed": bool(config.get("assistant_id"))
    })

@app.route("/api/config", methods=["POST"])
def api_config():
    data = request.json or {}
    config = get_config()

    p_key = data.get("vapi_private_key", "").strip()
    pub_key = data.get("vapi_public_key", "").strip()
    if p_key:
        set_secret("vapi_private_key", p_key)
    if pub_key:
        set_secret("vapi_public_key", pub_key)

    config["phone_number"] = data.get("phone_number", "").strip()
    config["google_calendar_id"] = data.get("google_calendar_id", "").strip()
    config["smtp_email"] = data.get("smtp_email", "").strip()

    smtp_pass = data.get("smtp_password", "").strip()
    if smtp_pass:
        set_secret("smtp_password", smtp_pass)

    # Sensitive fields go to runtime memory only — never to config.json on disk.
    oauth_cid = data.get("google_oauth_client_id", "").strip()
    if oauth_cid:
        set_secret("google_oauth_client_id", oauth_cid)
    oauth_sec = data.get("google_oauth_client_secret", "").strip()
    if oauth_sec:
        set_secret("google_oauth_client_secret", oauth_sec)
    p_key = data.get("vapi_private_key", "").strip()
    if p_key:
        set_secret("vapi_private_key", p_key)
    pub_key = data.get("vapi_public_key", "").strip()
    if pub_key:
        set_secret("vapi_public_key", pub_key)

    save_config(config)
    return jsonify({"success": True, "message": "Non-sensitive settings saved. Sensitive values are stored in memory only (use env vars on Render to persist across restarts)."})

@app.route("/api/upload-credentials", methods=["POST"])
def api_upload_credentials():
    data = request.json or {}
    file_type = data.get("type", "").strip()
    content = data.get("content", "").strip()

    if file_type not in ("google_credentials", "oauth_token"):
        return jsonify({"success": False, "message": "Invalid file type. Must be 'google_credentials' or 'oauth_token'."}), 400

    if not content:
        return jsonify({"success": False, "message": "No file content provided."}), 400

    try:
        parsed = json.loads(content)
    except Exception as e:
        return jsonify({"success": False, "message": f"Invalid JSON: {e}"}), 400

    secret_key = "google_credentials_json" if file_type == "google_credentials" else "oauth_token_json"
    set_secret(secret_key, json.dumps(parsed))
    print(f"{file_type}.json stored in memory ({len(content)} bytes). NOT written to disk.")
    return jsonify({"success": True, "message": f"{file_type}.json stored in memory only (will be lost on restart). Set GOOGLE_CREDENTIALS_JSON / OAUTH_TOKEN_JSON env var on Render to persist."})


@app.route("/api/credentials-status")
def api_credentials_status():
    return jsonify({
        "google_credentials_uploaded": secret_configured("google_credentials_json"),
        "oauth_token_uploaded": secret_configured("oauth_token_json"),
    })

# ==========================================
# Google OAuth User Authorization Flow
# ==========================================

OAUTH_SCOPES = ['https://www.googleapis.com/auth/calendar']
# Maps OAuth state token -> code_verifier, so the callback can complete PKCE.
OAUTH_FLOW_STATE = {}

# ==========================================
# Runtime Secrets (NOT persisted to disk)
# ==========================================
# Sensitive values are kept in memory only. They can be supplied via:
#   1. Environment variables (persisted across restarts in Render dashboard)
#   2. The Settings panel (in-memory only, lost on restart/redeploy)
# This avoids writing secrets to config.json or uploading credential files
# to the server's filesystem.

RUNTIME_SECRETS = {
    "vapi_private_key": None,
    "vapi_public_key": None,
    "google_oauth_client_id": None,
    "google_oauth_client_secret": None,
    "google_credentials_json": None,   # raw JSON string
    "oauth_token_json": None,          # raw JSON string
    "smtp_password": None,             # SMTP app password (sensitive, never persisted)
}

_SECRET_ENV_MAP = {
    "vapi_private_key": "VAPI_PRIVATE_KEY",
    "vapi_public_key": "VAPI_PUBLIC_KEY",
    "google_oauth_client_id": "GOOGLE_OAUTH_CLIENT_ID",
    "google_oauth_client_secret": "GOOGLE_OAUTH_CLIENT_SECRET",
    "google_credentials_json": "GOOGLE_CREDENTIALS_JSON",
    "oauth_token_json": "OAUTH_TOKEN_JSON",
    "smtp_password": "SMTP_PASSWORD",
}


def get_secret(key):
    """Read a secret from env var first, then runtime memory."""
    env_name = _SECRET_ENV_MAP.get(key)
    if env_name and os.environ.get(env_name):
        return os.environ.get(env_name)
    return RUNTIME_SECRETS.get(key)


def set_secret(key, value):
    """Store a secret in runtime memory only. Does NOT touch disk."""
    if key in RUNTIME_SECRETS:
        RUNTIME_SECRETS[key] = value


def secret_configured(key):
    return bool(get_secret(key))


def _build_oauth_client_config():
    redirect_uri = f"{PUBLIC_URL}/api/auth/google/callback"
    return {
        "web": {
            "client_id": (get_secret("google_oauth_client_id") or "").strip(),
            "client_secret": (get_secret("google_oauth_client_secret") or "").strip(),
            "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris": [redirect_uri]
        }
    }, redirect_uri


@app.route("/api/auth/google/start")
def api_auth_google_start():
    global OAUTH_FLOW_STATE
    client_id = (get_secret("google_oauth_client_id") or "").strip()
    client_secret = (get_secret("google_oauth_client_secret") or "").strip()

    if not client_id or not client_secret:
        return jsonify({
            "success": False,
            "message": "Google OAuth Client ID and Secret are not configured. Add them in Settings first."
        }), 400

    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError:
        return jsonify({
            "success": False,
            "message": "google-auth-oauthlib is not installed."
        }), 500

    client_config, redirect_uri = _build_oauth_client_config()
    flow = Flow.from_client_config(client_config, scopes=OAUTH_SCOPES, redirect_uri=redirect_uri)
    auth_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )
    OAUTH_FLOW_STATE[state] = flow.code_verifier
    return jsonify({"success": True, "auth_url": auth_url, "redirect_uri": redirect_uri})


@app.route("/api/auth/google/callback")
def api_auth_google_callback():
    global OAUTH_FLOW_STATE
    client_id = (get_secret("google_oauth_client_id") or "").strip()
    client_secret = (get_secret("google_oauth_client_secret") or "").strip()

    if not client_id or not client_secret:
        return "Error: OAuth client not configured.", 400

    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError:
        return "Error: google-auth-oauthlib not installed.", 500

    state = request.args.get("state")
    code_verifier = OAUTH_FLOW_STATE.pop(state, None) if state else None

    client_config, redirect_uri = _build_oauth_client_config()
    flow = Flow.from_client_config(
        client_config,
        scopes=OAUTH_SCOPES,
        redirect_uri=redirect_uri,
        state=state
    )

    try:
        if code_verifier:
            flow.fetch_token(authorization_response=request.url, code_verifier=code_verifier)
        else:
            flow.fetch_token(authorization_response=request.url)
    except Exception as e:
        return f"<h2>Authorization Failed</h2><p>{e}</p><p><a href='{PUBLIC_URL}'>Return to app</a></p>", 400

    credentials = flow.credentials
    token_data = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": list(credentials.scopes) if credentials.scopes else OAUTH_SCOPES,
        "type": "authorized_user"
    }

    set_secret("oauth_token_json", json.dumps(token_data))
    print("OAuth token stored in memory only (NOT written to disk).")

    return f"""<!DOCTYPE html>
<html><head><title>Google Connected</title>
<style>body{{font-family:system-ui;background:#0f172a;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}
.card{{background:rgba(0,230,118,0.1);border:1px solid #00e676;padding:40px;border-radius:12px;text-align:center;max-width:500px}}
h2{{color:#00e676;margin:0 0 15px}}
a{{display:inline-block;margin-top:20px;padding:10px 20px;background:#00e676;color:#000;border-radius:6px;text-decoration:none;font-weight:600}}</style>
</head><body><div class="card">
<h2>Google Account Connected</h2>
<p>Your Google Calendar authorization has been saved. You can close this tab and return to the app.</p>
<a href="{PUBLIC_URL}">Return to Dashboard</a>
</div></body></html>"""

@app.route("/api/debug/oauth-token", methods=["GET"])
def api_debug_oauth_token():
    token_json = get_secret("oauth_token_json")
    if not token_json:
        return jsonify({"configured": False, "error": "No OAuth token in memory. Click 'Connect Google Account' first."}), 404
    try:
        parsed = json.loads(token_json) if isinstance(token_json, str) else token_json
        return jsonify({"configured": True, "token_json": parsed})
    except Exception as e:
        return jsonify({"configured": True, "raw": token_json, "parse_error": str(e)}), 200

@app.route("/api/calendar")
def api_calendar():
    return jsonify(get_calendar())

@app.route("/api/calendar/reset", methods=["POST"])
def api_calendar_reset():
    # Attempt to clean up Google Calendar events before resetting local DB
    config = get_config()
    calendar_id = config.get("google_calendar_id")
    service = get_calendar_service()
    
    if service and calendar_id:
        try:
            # Fetch events for the next 10 days to clean up
            now = datetime.datetime.now(datetime.timezone.utc)
            time_min = now.isoformat()
            time_max = (now + datetime.timedelta(days=10)).isoformat()
            
            events_result = service.events().list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True
            ).execute()
            events = events_result.get('items', [])
            
            for event in events:
                desc = event.get('description', '') or ''
                summary = event.get('summary', '') or ''
                # Identify events created by the assistant
                if "Interview booked by Shaan's AI Assistant" in desc or ("Interview: " in summary and "x Shaan Raza" in summary):
                    try:
                        event_id = event.get('id')
                        print(f"Deleting Google Calendar event: {event_id} ({summary})")
                        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
                    except Exception as ex:
                        print(f"Failed to delete event {event.get('id')}: {ex}")
        except Exception as e:
            print(f"Error listing calendar events during reset: {e}")
                    
    init_calendar(force=True)
    save_contacts([])
    save_logs([])
    return jsonify({"success": True, "calendar": get_calendar()})

@app.route("/api/logs")
def api_logs():
    return jsonify(get_logs())

@app.route("/api/contacts")
def api_contacts():
    return jsonify(get_contacts())

@app.route("/api/contacts/<contact_id>", methods=["PUT"])
def api_update_contact(contact_id):
    data = request.json or {}
    contacts = get_contacts()
    updated = False
    for c in contacts:
        if c.get("id") == contact_id:
            if "status" in data:
                c["status"] = data["status"]
            if "notes" in data:
                c["notes"] = data["notes"]
            updated = True
            break
    if updated:
        save_contacts(contacts)
        return jsonify({"success": True, "message": "Lead status updated."})
    else:
        return jsonify({"success": False, "message": "Contact not found."}), 404

@app.route("/api/contacts/download")
def download_contacts():
    import csv
    from io import StringIO
    from flask import make_response
    
    contacts = get_contacts()
    si = StringIO()
    # Write UTF-8 BOM so Excel opens it with correct formatting
    si.write('\ufeff')
    cw = csv.writer(si)
    
    # Headers
    cw.writerow(["Name", "Email", "Phone Number", "Date", "Time", "Calendar Invite Link", "Google Meet Link", "Created At"])
    
    # Write data
    for c in contacts:
        email = c.get("email") or c.get("contact") or "N/A"
        phone = c.get("phone") or "N/A"
        cw.writerow([
            c.get("name", "Unknown"),
            email,
            phone,
            c.get("date", "N/A"),
            c.get("time", "N/A"),
            c.get("google_event_link", "N/A"),
            c.get("google_meet_link", "N/A"),
            c.get("created_at", "")
        ])
        
    response = make_response(si.getvalue())
    response.headers["Content-Disposition"] = "attachment; filename=leads_report.csv"
    response.headers["Content-type"] = "text/csv; charset=utf-8"
    return response

def deploy_assistant_to_vapi(private_key, public_url, config):
    headers = {
        "Authorization": f"Bearer {private_key}",
        "Content-Type": "application/json"
    }
    
    # We will fetch existing assistants to see if one named "Shaan's AI Assistant" exists
    assistant_id = config.get("assistant_id")
    assistant_exists = False
    
    # Load Shaan's resume if resume.txt exists in the project directory
    shaan_resume = ""
    if os.path.exists("resume.txt"):
        try:
            with open("resume.txt", "r") as rf:
                shaan_resume = rf.read().strip()
            print("Successfully loaded Shaan's resume from resume.txt.")
        except Exception as e:
            print(f"Error reading resume.txt: {e}")
            
    if not shaan_resume:
        shaan_resume = """Candidate Name: Shaan Raza
Role: Data Analyst & Business Analyst
Core Skills: 
- Languages & Analytics: Python (Pandas, NumPy, Scikit-Learn), SQL (Joins, CTEs, Window Functions), Excel, Web Scraping (Selenium, BeautifulSoup)
- Visualization & BI: Power BI (PL-300 Certified), Tableau
- Data Platforms: MySQL, Snowflake, Hadoop, Hive
Key Experience: 
- Crystal Technology Services: Business Analyst Intern. Process flows for IVR/voicebot automation, CSAT/AHT analytics, BRDs/FRDs.
- Carbon Crunch: Data Analyst Intern. Analyzing scope 1, 2, 3 emissions with SQL/Python, web scraping automation for CPCB portal.
Key Projects:
- Zomato Dataset Analysis (SQL, Pandas)
- RTDMS Automation Scraper (Selenium, BeautifulSoup)
- Carbon Crunch emissions tracker dashboard (Power BI)
- FMCG Customer Churn Prediction (XGBoost, RFM analysis)
Why Shaan is a fit: Shaan has a strong blend of data analysis and workflow automation skills. He is highly self-driven, detail-oriented, and has solved over 150+ SQL queries.
"""

    # Dynamically format current IST date/day
    ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    now_ist = datetime.datetime.now(ist_tz)
    current_date_str = now_ist.strftime("%Y-%m-%d (%A)")
    today_formatted = now_ist.strftime("%B %d, %Y")

    # Define our assistant payload
    system_prompt = f"""You are the AI Representative for Shaan Raza, a Data Analyst and Business Analyst with experience in analytics, Python, SQL, automation, and data-driven problem solving. Your goal is to represent Shaan in scheduling interviews with recruiters and hiring managers, answering questions about Shaan's background, skills, and projects, and booking the interview slot.

Key Context:
- Current date: {current_date_str}. Today is {today_formatted}. Keep this in mind when proposing slots.
- Candidate Name: Shaan Raza. Always refer to candidate using only his first name 'Shaan' (e.g., 'Shaan's AI representative'). If you ever need to say his full name, it is strictly 'Shaan Raza'. Under no circumstances should you ever use other surnames like 'Rosa' or 'dazar' or misspell it.
- Shaan's Background and Experience:
{shaan_resume}

Behavioral Guidelines:
- Introduce yourself naturally as Shaan's AI representative: "Hi, I'm Shaan's AI representative. Shaan is a Data Analyst and Business Analyst with experience in analytics, Python, SQL, automation, and data-driven problem solving. I'm here to answer questions about his background, projects, and skills, and can also help schedule an interview. Who do I have the pleasure of speaking with?"
- Maintain a warm, professional, and helpful tone.
- Be concise and punchy in your speech. Speak in short paragraphs. Avoid long blocks of text which sound unnatural on a phone call.
- Handle interruptions gracefully. If the candidate speaks over you, stop talking and listen.
- Negative Factual Questions & Candidate Profile Scope:
  Questions about Shaan's employment history, education, internships, projects, skills, experience, companies worked for, job titles, or qualifications (for example, "Did Shaan work at Google?", "Is Shaan a Senior Software Engineer?", "Is Shaan an AI Engineer?", "Has Shaan worked at Microsoft?", "Does Shaan have 10 years of experience?") must NOT be classified as off-topic or out of scope.
  These are valid questions about Shaan's background. If there is no evidence of these in Shaan's resume or profile, do not say the question is off-topic. Instead, answer using the available evidence with a clear, direct, and polite negative response.
  Examples:
  - Question: "Did Shaan work at Google?" -> Response: "No. Based on the available information, Shaan has not worked at Google."
  - Question: "Is Shaan a Senior Software Engineer?" -> Response: "No. Shaan's background is in Data Analytics and Business Analysis."
  - Question: "Is Shaan an AI Engineer?" -> Response: "No. Shaan is currently a Data Analyst and Business Analyst. He is interested in AI and building AI projects, but should not be represented as an experienced AI Engineer."
  - Question: "Has Shaan worked at Microsoft?" -> Response: "No. Shaan has not worked at Microsoft."
  - Question: "Does Shaan have 10 years of experience?" -> Response: "No. Shaan has interned as a Business Analyst and Data Analyst during his university studies, so he does not have 10 years of experience."
- Off-script/Off-topic conversations:
  If the caller asks an off-script, irrelevant, or casual question (e.g., "how to make a sandwich", "what is the weather", "tell me a joke", or other non-resume/non-career questions):
  - Do NOT answer the question under any circumstances. Do NOT list steps, recipes, or general information.
  - Politely and directly state that this is an off-topic question and that you are only programmed to discuss Shaan's qualifications, resume, and scheduling.
  - Immediately pivot the conversation back to Shaan's resume or scheduling.
  - Example: "I'm sorry, but that is an off-topic question. I am programmed to only discuss Shaan's resume, background, and scheduling. Let's get back to that—would you like to hear about Shaan's projects or should we schedule an interview?"
- Recover gracefully when you don't know something: Say so honestly (do not invent information), and offer to schedule a call so they can ask Shaan directly.
- When scheduling:
  - IMPORTANT: You already know the interviewer's name (passed via variable `interviewer_name`). Do NOT ask the interviewer to provide their name under any circumstances.
  - When scheduling, you MUST ask the interviewer for:
    1. Their email address.
    2. Their phone number.
  - If the interviewer refuses to provide their phone number (e.g., says "no" or "I don't want to"), use "NA" as their phone number when calling the booking tool. Under no circumstances should you ever use Shaan's phone number (+91-8826112919) as the interviewer's phone number.
  - Spoken Email Capture:
    Callers may say their email address with spaces, words, or spell it out (e.g. "s h a a n r a z a zero zero zero seven at gmail dot com" or "shaan raza 0007 at gmail.com").
    When passing this to the booking tool, make sure to pass the email as a single continuous string. Do not include spaces or word spellings in the booking tool parameter (e.g. pass it as "shaanraza0007@gmail.com").
  - Reverifying details by spelling them:
    Once they provide their email address and phone number, you MUST read them back to verify them by spelling them out clearly:
    - CRITICAL: Never use hyphens (-) or dashes when spelling out names, letters, or numbers. The text-to-speech engine will speak hyphens aloud as "minus", which confuses the caller. Instead, strictly separate letters and digits with single spaces only.
    - Spell out the email character-by-character using single spaces (e.g., "So that is s h a a n r a z a 0 0 0 7 at g m a i l dot c o m, correct?").
    - Spell out the phone number digit-by-digit using single spaces (e.g., "And the phone number is 1 2 3 4 5 6 7 8 9 0?").
    - MANDATORY: You MUST spell out the email and get explicit confirmation ("yes" / "correct" / "that's right") from the caller BEFORE calling the book_interview_slot tool. If the caller does not explicitly confirm, ASK AGAIN. Do not proceed without confirmation. A single misheard letter (e.g., hearing "max25" instead of "max2five", or "shaanthegreat" instead of "shaanthgreat") will cause the calendar invite to fail with a 550 email error.
    - Only proceed to check availability and book the slot once they confirm these details are correct.
    - CRITICAL EMAIL RULE: The interviewer's email address MUST come from what the interviewer (caller) explicitly dictates during the call. NEVER invent, guess, fill in, or default an email from your own context, your system prompt, your profile, or Shaan's contact information. If the interviewer refuses to provide an email, has not yet given one, or is unclear, you MUST pass an empty string "" as `interviewer_email` to the booking tool. Shaan's own email addresses (e.g. shaanraza0007@gmail.com, shaanraza2003@gmail.com, or any other email from your instructions) must NEVER be used as the interviewer's email under any circumstances.
    - CRITICAL: NEVER say the email is "invalid", "incorrect", "not valid", or reject it for any reason. There is no email validation in this system. Whatever email the caller provides — even if it sounds unusual, has extra words, or has minor pronunciation issues — you MUST pass it as a single continuous string to the booking tool (e.g. "max25 at gmail.com" should be passed as "max25@gmail.com"). If you are genuinely unsure what they said, ASK them to repeat it letter by letter, but never refuse to book the slot claiming the email is invalid. The system will handle email normalization automatically.
  - Follow these steps to schedule:
    1. Ask the interviewer for their email address (do NOT ask for their name as you already have it). If they refuse or don't provide one, accept it and continue — do not invent one from your context.
    2. Ask the interviewer for their phone number (use 'NA' if they refuse/say no).
    3. If an email was provided, spell it out character-by-character and the phone number digit-by-digit to verify them and get their explicit confirmation.
    4. Call the `check_calendar_availability` tool to see what slots are open.
    5. Propose specific slots to the interviewer (e.g., "I see Shaan is free next Monday, June 8 at 11:00 AM or Tuesday, June 9 at 2:00 PM. Do either of those work?").
    6. If they suggest a different time, check if it's available or offer the closest available options.
    7. Once they agree on a slot, call the `book_interview_slot` tool. Pass the `interviewer_name` you were given, the `interviewer_email` the interviewer explicitly provided during this call (or an empty string "" if they refused), the phone number they gave you (or 'NA' if they refused), along with the date and time.
    8. Confirm the booking to the interviewer once the tool returns success.
    9. Once the booking is confirmed and you have said thank you or goodbye, call the `endCall` tool to automatically hang up and end the call.
"""

    assistant_payload = {
        "name": "Shaan's AI Assistant",
        "firstMessage": "Hi! I'm Shaan's AI representative. Shaan is a Data Analyst and Business Analyst with experience in analytics, Python, SQL, automation, and data-driven problem solving. I'm here to answer questions about his background, projects, and skills, and can also help schedule an interview. Who do I have the pleasure of speaking with?",
        "firstMessageInterruptionsEnabled": True,
        "serverUrl": f"{public_url}/api/webhook",
        "model": {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                }
            ],
            "tools": [
                {
                    "type": "endCall"
                },
                {
                    "type": "function",
                    "function": {
                        "name": "check_calendar_availability",
                        "description": "Checks available interview slots. You can optionally filter by a specific date (YYYY-MM-DD). If no date is provided, it returns all available slots for the next few days.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "date": {
                                    "type": "string",
                                    "description": "Optional date in YYYY-MM-DD format (e.g., 2026-06-08) to filter availability."
                                }
                            }
                        }
                    },
                    "server": {
                        "url": f"{public_url}/api/webhook"
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "book_interview_slot",
                        "description": "Books a confirmed interview slot for the interviewer.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "interviewer_name": {
                                    "type": "string",
                                    "description": "The full name of the interviewer."
                                },
                                "interviewer_email": {
                                    "type": "string",
                                    "description": "The email address of the interviewer."
                                },
                                "interviewer_phone": {
                                    "type": "string",
                                    "description": "The phone number of the interviewer."
                                },
                                "date": {
                                    "type": "string",
                                    "description": "The date of the interview in YYYY-MM-DD format (e.g., 2026-06-08)."
                                },
                                "time": {
                                    "type": "string",
                                    "description": "The time slot to book (e.g., 10:00 AM, 02:00 PM)."
                                }
                            },
                            "required": ["interviewer_name", "interviewer_email", "interviewer_phone", "date", "time"]
                        }
                    },
                    "server": {
                        "url": f"{public_url}/api/webhook"
                    }
                }
            ]
        },
        "voice": {
            "provider": "vapi",
            "voiceId": "Savannah"
        },
        "transcriber": {
            "provider": "deepgram",
            "model": "nova-2-general"
        }
    }
    
    # Check if current assistant_id in config is valid on Vapi
    if assistant_id:
        try:
            get_res = requests.get(f"https://api.vapi.ai/assistant/{assistant_id}", headers=headers)
            if get_res.status_code == 200:
                assistant_exists = True
        except Exception:
            pass
                
    if not assistant_exists:
        # Search by name first in Vapi assistants list
        list_res = requests.get("https://api.vapi.ai/assistant", headers=headers)
        if list_res.status_code == 200:
            assistants = list_res.json()
            for ast in assistants:
                if ast.get("name") == "Shaan's AI Assistant":
                    assistant_id = ast.get("id")
                    assistant_exists = True
                    break
                    
    if assistant_exists:
        # Update existing assistant
        print(f"Updating existing Vapi assistant: {assistant_id}")
        deploy_res = requests.patch(f"https://api.vapi.ai/assistant/{assistant_id}", headers=headers, json=assistant_payload)
    else:
        # Create a new assistant
        print("Creating new Vapi assistant...")
        deploy_res = requests.post("https://api.vapi.ai/assistant", headers=headers, json=assistant_payload)
        
    if deploy_res.status_code not in [200, 201]:
        raise Exception(f"Failed to deploy assistant: {deploy_res.text}")
        
    assistant_data = deploy_res.json()
    new_assistant_id = assistant_data.get("id")
    
    # Save configured assistant ID
    config["assistant_id"] = new_assistant_id
    save_config(config)
    
    # Optionally link phone number if configured
    phone_msg = ""
    phone_number = config.get("phone_number")
    if phone_number:
        nums_res = requests.get("https://api.vapi.ai/phone-number", headers=headers)
        if nums_res.status_code == 200:
            phone_list = nums_res.json()
            matched_phone_id = None
            for phone in phone_list:
                p_num = phone.get("number", "").replace("+", "").replace("-", "").replace(" ", "")
                user_num = phone_number.replace("+", "").replace("-", "").replace(" ", "")
                if user_num in p_num or p_num in user_num or phone.get("id") == phone_number:
                    matched_phone_id = phone.get("id")
                    break
            
            if matched_phone_id:
                print(f"Linking phone number {matched_phone_id} to assistant {new_assistant_id}...")
                link_res = requests.patch(
                    f"https://api.vapi.ai/phone-number/{matched_phone_id}",
                    headers=headers,
                    json={"assistantId": new_assistant_id}
                )
                if link_res.status_code in [200, 201]:
                    phone_msg = f" Also linked to phone number ID: {matched_phone_id}."
                else:
                    phone_msg = f" (Warning: Failed to link phone number: {link_res.text})"
            else:
                phone_msg = " (Warning: Phone number not found in Vapi account to link.)"
        else:
            phone_msg = " (Warning: Failed to fetch Vapi phone numbers list.)"
            
    return new_assistant_id, phone_msg

@app.route("/api/deploy", methods=["POST"])
def api_deploy():
    config = get_config()
    private_key = config.get("vapi_private_key")
    
    if not private_key:
        return jsonify({"success": False, "message": "Vapi Private API Key is not configured."}), 400
        
    try:
        new_assistant_id, phone_msg = deploy_assistant_to_vapi(private_key, PUBLIC_URL, config)
        return jsonify({
            "success": True, 
            "message": f"Assistant successfully deployed with ID: {new_assistant_id}.{phone_msg}",
            "assistant_id": new_assistant_id
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

# ==========================================
# Vapi Webhook Route
# ==========================================

def process_post_call_analysis(call_id, recording_url=None, summary_text=None):
    if not call_id:
        return
        
    time.sleep(2)  # Wait for transcript to settle
    print(f"Running post-call analysis for call {call_id}...")
    
    # 1. Update call status in logs if needed
    logs = get_logs()
    transcript = []
    for log in logs:
        if log.get("call_id") == call_id:
            transcript = log.get("transcript", [])
            if log.get("status") != "ended":
                log["status"] = "ended"
                save_logs(logs)
            break
            
    # 2. Update contact details
    contacts = get_contacts()
    contact_found = None
    for c in contacts:
        if c.get("call_id") == call_id:
            contact_found = c
            break
            
    # Heuristic NLP parser targeting transcription patterns
    pos_words = ["great", "excellent", "awesome", "perfect", "good", "happy", "excited", "impressed", "wonderful", "cool", "nice"]
    neg_words = ["reject", "sorry", "unfortunately", "cancel", "fail", "bad", "disappointed", "negative", "no", "not a fit"]
    
    pos_count = 0
    neg_count = 0
    full_text = " ".join([m.get("text", "").lower() for m in transcript])
    
    for w in pos_words:
        pos_count += len(re.findall(rf"\b{w}\b", full_text))
    for w in neg_words:
        neg_count += len(re.findall(rf"\b{w}\b", full_text))
        
    sentiment = "Neutral"
    if pos_count > neg_count + 1:
        sentiment = "Positive"
    elif neg_count > pos_count:
        sentiment = "Negative"
        
    prep_items = []
    tech_terms = ["Python", "Flask", "React", "Vanilla", "CSS", "Javascript", "OpenAI", "Gemini", "Vapi", "Google Calendar", "SQL", "Docker", "Git", "AI"]
    
    for msg in transcript:
        if msg.get("role") == "user":
            text = msg.get("text", "")
            if "?" in text or text.lower().strip().startswith(("what", "how", "why", "can you", "could you", "tell me")):
                clean_q = text.strip()
                if clean_q and clean_q not in prep_items:
                    prep_items.append(clean_q)
                    
    tech_found = []
    for term in tech_terms:
        if re.search(rf"\b{term}\b", full_text, re.IGNORECASE):
            tech_found.append(term)
            
    if tech_found:
        prep_items.append(f"Tech Stack Interests: Discussed {', '.join(tech_found)}.")
        
    if not prep_items:
        prep_items = ["General intro call - standard background review.", "Follow up on software engineering qualifications."]
        
    if not summary_text:
        summary_text = "Standard introduction call completed."
        if len(transcript) > 0:
            summary_text = f"Voice interaction completed with {len(transcript)} exchanges."
            if contact_found:
                summary_text += f" Scheduled an interview for {contact_found.get('name')} on {contact_found.get('date')} at {contact_found.get('time')}."
                
    if contact_found:
        contact_found["recording_url"] = recording_url or ""
        contact_found["sentiment"] = sentiment
        contact_found["summary"] = summary_text
        contact_found["prep_sheet"] = prep_items
        if "notes" not in contact_found:
            contact_found["notes"] = ""
        if "status" not in contact_found:
            contact_found["status"] = "Scheduled"
        save_contacts(contacts)
        print(f"Contact details updated with post-call intelligence for call {call_id}.")
    else:
        # Fallback extraction if booking wasn't triggered
        extracted_email = None
        extracted_phone = None
        extracted_name = None
        
        email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', full_text)
        if email_match:
            extracted_email = email_match.group(0)
            
        phone_match = re.search(r'\+?\d{1,4}[-.\s]?\(?\d{1,3}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{1,9}', full_text)
        if phone_match and len(re.sub(r'\D', '', phone_match.group(0))) >= 10:
            extracted_phone = phone_match.group(0)
            
        name_match = re.search(r"(?:my name is|i am|this is)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", " ".join([m.get("text", "") for m in transcript]))
        if name_match:
            extracted_name = name_match.group(1)
            
        if extracted_name or extracted_email or extracted_phone:
            import uuid
            new_id = str(uuid.uuid4())
            contacts.append({
                "id": new_id,
                "name": extracted_name or "Anonymous Recruiter",
                "email": extracted_email or "N/A",
                "phone": extracted_phone or "N/A",
                "date": "N/A",
                "time": "N/A",
                "google_event_link": "",
                "google_meet_link": "",
                "call_id": call_id,
                "status": "Inquiry",
                "notes": "Extracted from general inquiry call.",
                "sentiment": sentiment,
                "summary": summary_text,
                "prep_sheet": prep_items,
                "recording_url": recording_url or "",
                "created_at": datetime.datetime.now().isoformat()
            })
            save_contacts(contacts)
            print(f"Created new inquiry contact entry for call {call_id}.")

@app.route("/api/webhook", methods=["POST"])
def api_webhook():
    payload = request.json or {}
    print(f"Webhook Received: {json.dumps(payload)[:200]}...") # Log start of payload
    
    message = payload.get("message", {})
    message_type = message.get("type")
    
    if not message_type:
        # Sometimes structure is flat
        message_type = payload.get("type")
        
    call = payload.get("call", {}) or message.get("call", {})
    call_id = call.get("id") if call else None
    
    # 1. Handle Tool Calls
    if message_type == "tool-calls":
        tool_calls = message.get("toolCalls", [])
        results = []
        
        for tool in tool_calls:
            tool_id = tool.get("id")
            func = tool.get("function", {})
            name = func.get("name")
            args = func.get("arguments")
            
            # Arguments can be JSON string or dict
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
                    
            result_str = ""
            if name == "check_calendar_availability":
                date_val = args.get("date")
                result_str = handle_check_calendar(date_val)
            elif name == "book_interview_slot":
                int_name = args.get("interviewer_name") or args.get("candidate_name") or "Unknown"
                int_email = args.get("interviewer_email") or args.get("candidate_email")
                int_phone = args.get("interviewer_phone") or args.get("candidate_phone")
                cand_contact = args.get("candidate_contact")
                date_val = args.get("date")
                time_val = args.get("time")
                result_str = handle_book_slot(int_name, date_val, time_val, interviewer_email=int_email, interviewer_phone=int_phone, candidate_contact=cand_contact, call_id=call_id)
            else:
                result_str = f"Error: Tool {name} not recognized."
                
            results.append({
                "toolCallId": tool_id,
                "result": result_str
            })
            
        print(f"Responding to Tool Calls: {results}")
        return jsonify({"results": results}), 201
        
    # 2. Handle Status Update
    elif message_type == "status-update":
        status = message.get("status") or call.get("status")
        if call_id and status:
            update_call_status(call_id, status)
        return "", 200
        
    # 3. Handle Conversation Update (for real-time transcripts sync)
    elif message_type == "conversation-update":
        conversation = message.get("conversation", [])
        if call_id and conversation:
            logs = get_logs()
            call_record = None
            for log in logs:
                if log.get("call_id") == call_id:
                    call_record = log
                    break
            if not call_record:
                call_record = {
                    "call_id": call_id,
                    "status": "in-progress",
                    "timestamp": datetime.datetime.now().isoformat(),
                    "transcript": []
                }
                logs.append(call_record)
                
            # Clear and rebuild from conversation list to keep in sync
            call_record["transcript"] = []
            for msg_item in conversation:
                role = msg_item.get("role")
                if role == "system":
                    continue
                role_label = 'assistant' if role == 'assistant' else 'user'
                content = msg_item.get("content") or msg_item.get("text") or ""
                if content:
                    content = sanitize_spelling(content)
                    call_record["transcript"].append({
                        "role": role_label,
                        "text": content,
                        "timestamp": datetime.datetime.now().isoformat()
                    })
            save_logs(logs)
            print(f"[Call {call_id}] Webhook conversation-update processed: {len(call_record['transcript'])} messages.")
        return "", 200
        
    # 4. Handle End of Call Report Webhook
    elif message_type == "end-of-call-report":
        recording_url = call.get("recordingUrl") or message.get("recordingUrl") or payload.get("recordingUrl")
        summary_text = call.get("summary") or message.get("summary") or payload.get("summary")
        t = threading.Thread(target=process_post_call_analysis, args=(call_id, recording_url, summary_text))
        t.daemon = True
        t.start()
        return "", 200
        
    # 5. Handle Transcripts
    elif message_type in ["transcript", "speech-update"]:
        role = message.get("role")
        text = message.get("transcript") or message.get("text")
        
        # Some webhooks pass text list or other structures
        if not text and "transcript" in payload:
            text = payload.get("transcript")
            
        if call_id and role and text:
            if role == "assistant":
                # Ignore assistant STT transcription to avoid spoken spelling errors (conversation-update has the clean LLM text version)
                pass
            else:
                add_log_message(call_id, role, text)
        return "", 200
        
    return "", 200

# ==========================================
# Startup Bootstrap (env-var driven auto-deploy & auto-connect)
# ==========================================
# When the following env vars are set in Render, the app no longer requires
# any manual clicks in the Settings panel:
#   - VAPI_PRIVATE_KEY             (required for auto-deploy)
#   - GOOGLE_OAUTH_CLIENT_ID       (required for Google Calendar)
#   - GOOGLE_OAUTH_CLIENT_SECRET   (required for Google Calendar)
#   - GOOGLE_CREDENTIALS_JSON      (raw JSON string of google_credentials.json)
#   - OAUTH_TOKEN_JSON             (raw JSON string of oauth_token.json)
#   - GOOGLE_CALENDAR_ID           (e.g. you@gmail.com)
#   - PHONE_NUMBER                 (Vapi phone number ID, optional)
#   - SMTP_EMAIL                   (for SMTP backup email)
#   - SMTP_PASSWORD                (16-char Gmail app password)

def _bootstrap_auto_deploy():
    """Background thread: deploy (or re-deploy) the Vapi assistant on startup.

    Validates the stored assistant_id against the current Vapi account. If it no
    longer exists (e.g. user switched Vapi accounts), deploys a new one.
    """
    try:
        config = get_config()
        private_key = get_secret("vapi_private_key")
        if not private_key:
            print("[bootstrap] No VAPI_PRIVATE_KEY env var — skipping auto-deploy. Use the Settings panel.")
            return

        assistant_id = config.get("assistant_id")
        if assistant_id:
            # Quick validation: does the stored assistant still exist on this Vapi account?
            try:
                r = requests.get(
                    f"https://api.vapi.ai/assistant/{assistant_id}",
                    headers={"Authorization": f"Bearer {private_key}"},
                    timeout=10
                )
                if r.status_code == 200:
                    print(f"[bootstrap] Assistant {assistant_id} is valid — skipping redeploy.")
                    return
                else:
                    print(f"[bootstrap] Stored assistant_id {assistant_id} returned HTTP {r.status_code} — re-deploying (likely new Vapi account).")
            except Exception as e:
                print(f"[bootstrap] Could not validate assistant_id ({e}) — re-deploying to be safe.")

        print("[bootstrap] Auto-deploying Vapi assistant...")
        new_id, phone_msg = deploy_assistant_to_vapi(private_key, PUBLIC_URL, config)
        print(f"[bootstrap] Auto-deploy complete: {new_id}{phone_msg}")
    except Exception as e:
        print(f"[bootstrap] Auto-deploy FAILED: {e}")


def _verify_google_calendar():
    """Background: verify the Google Calendar service account can list events.

    Catches the most common setup mistake (service account not shared with the
    calendar) at startup instead of at first booking attempt.
    """
    try:
        creds_json = get_secret("google_credentials_json")
        if not creds_json:
            return  # user OAuth path; nothing to verify here
        service = get_calendar_service()
        if not service:
            print("[bootstrap] Google Calendar: service account present but get_calendar_service() returned None.")
            return
        calendar_id = (os.environ.get("GOOGLE_CALENDAR_ID") or "").strip()
        if not calendar_id:
            print("[bootstrap] Google Calendar: service account OK, but GOOGLE_CALENDAR_ID not set.")
            return
        # Lightweight call — just list 1 upcoming event
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        service.events().list(calendarId=calendar_id, maxResults=1, timeMin=now, singleEvents=True).execute()
        print(f"[bootstrap] Google Calendar: service account verified for '{calendar_id}' ✓")
    except Exception as e:
        err = str(e)
        if "404" in err or "notFound" in err:
            print(f"[bootstrap] Google Calendar: 404 — the service account email is not shared with calendar '{calendar_id}'.")
            print(f"[bootstrap]   Fix: open Google Calendar → Settings → Share with specific people → add the service account email as 'Make changes to events'.")
        elif "403" in err:
            print(f"[bootstrap] Google Calendar: 403 — service account lacks permission. Check that Calendar API is enabled in the GCP project.")
        else:
            print(f"[bootstrap] Google Calendar verification failed: {e}")


def bootstrap_runtime():
    """Log runtime state and kick off background auto-deploy if env vars are configured."""
    print("=" * 60)
    print("[bootstrap] Runtime configuration:")
    print(f"  - VAPI_PRIVATE_KEY:        {'set' if get_secret('vapi_private_key') else 'MISSING'}")
    print(f"  - VAPI_PUBLIC_KEY:         {'set' if get_secret('vapi_public_key') else 'MISSING'}")
    print(f"  - PHONE_NUMBER:            {os.environ.get('PHONE_NUMBER') or '(unset)'}")
    print(f"  - GOOGLE_CALENDAR_ID:      {os.environ.get('GOOGLE_CALENDAR_ID') or '(unset)'}")
    print(f"  - GOOGLE_CREDENTIALS_JSON: {'set' if get_secret('google_credentials_json') else 'MISSING'}")
    print(f"  - OAUTH_TOKEN_JSON:        {'set' if get_secret('oauth_token_json') else 'MISSING'}")
    print(f"  - GOOGLE_OAUTH_CLIENT_ID:  {'set' if get_secret('google_oauth_client_id') else 'MISSING'}")
    print(f"  - SMTP_EMAIL:              {os.environ.get('SMTP_EMAIL') or '(unset)'}")
    print(f"  - SMTP_PASSWORD:           {'set' if get_secret('smtp_password') else 'MISSING (no SMTP backup email)'}")

    # Show which Google auth method is active
    if get_secret("google_credentials_json"):
        print("[bootstrap] Google auth: SERVICE ACCOUNT (recommended, no refresh_token issues).")
    elif get_secret("oauth_token_json"):
        print("[bootstrap] Google auth: user OAuth token. (Will fail if token is missing refresh_token.)")
    else:
        print("[bootstrap] Google auth: NONE — Calendar will not work.")

    if get_secret("vapi_private_key"):
        # Run deploy in background so startup isn't blocked by the Vapi API.
        t = threading.Thread(target=_bootstrap_auto_deploy, daemon=True)
        t.start()

    # Verify Google Calendar connectivity in the background
    t = threading.Thread(target=_verify_google_calendar, daemon=True)
    t.start()

    print("=" * 60)


# ==========================================
# Main Execution Entry
# ==========================================

if __name__ == "__main__":
    # Ensure stores are configured
    init_config()
    init_calendar()
    init_logs()
    init_contacts()

    # Start Flask Server
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting Flask application on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=False)
else:
    # Running under gunicorn (Render production): run bootstrap on module import
    init_config()
    init_calendar()
    init_logs()
    init_contacts()
    bootstrap_runtime()
