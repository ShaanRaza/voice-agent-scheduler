import os
import json
import time
import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build

def parse_slot_time(date_str, time_str):
    try:
        dt_str = f"{date_str} {time_str}"
        naive_dt = datetime.datetime.strptime(dt_str, "%Y-%m-%d %I:%M %p")
        ist_tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        return naive_dt.replace(tzinfo=ist_tz)
    except Exception as e:
        print(f"Error parsing slot datetime ({date_str} {time_str}): {e}")
        return None

def test_calendar():
    creds_path = "google_credentials.json"
    if not os.path.exists(creds_path):
        return
    scopes = ['https://www.googleapis.com/auth/calendar']
    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=scopes)
    service = build('calendar', 'v3', credentials=creds)

    config_path = "config.json"
    with open(config_path, "r") as f:
        config = json.load(f)
    calendar_id = config.get("google_calendar_id")
    
    try:
        date_str = "2026-06-08"
        time_str = "12:00 PM"
        candidate_name = "Jane Recruiter"
        candidate_email = "recruiter@test.com"
        candidate_phone = "+1-555-0199"
        
        slot_start = parse_slot_time(date_str, time_str)
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
        
        event_body_with_attendees = event_body.copy()
        if candidate_email and "@" in candidate_email:
            event_body_with_attendees['attendees'] = [{'email': candidate_email.strip()}]
            
        try:
            print(f"Attempting to write event to calendar {calendar_id} with recruiter attendee...")
            event = service.events().insert(
                calendarId=calendar_id,
                body=event_body_with_attendees,
                sendUpdates='all'
            ).execute()
            print("PASS: Created event with attendee!")
        except Exception as api_err:
            err_msg = str(api_err)
            if "forbiddenForServiceAccounts" in err_msg or "Delegation of Authority" in err_msg or "403" in err_msg:
                print("Service account attendee invitation forbidden. Falling back to inserting event without attendees...")
                event = service.events().insert(
                    calendarId=calendar_id,
                    body=event_body
                ).execute()
                print("PASS: Created calendar event on Shaan's calendar without attendees.")
            else:
                raise api_err
                
        print(f"Event ID: {event.get('id')}")
        print(f"HTML Link: {event.get('htmlLink')}")
        
    except Exception as e:
        print(f"FAIL: {e}")

if __name__ == "__main__":
    test_calendar()
