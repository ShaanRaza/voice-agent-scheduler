import sys
import os

# Append project directory to path so we can import app helpers
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import get_calendar_service, get_config

def test_connection():
    print("=== Google Calendar Connection Verification ===")
    config = get_config()
    calendar_id = config.get("google_calendar_id")
    
    if not calendar_id:
        # Fallback to user's calendar email for verification
        calendar_id = "shaanraza0007@gmail.com"
        print(f"Calendar ID not set in config.json. Testing with default: {calendar_id}")
    else:
        print(f"Connected Calendar ID: {calendar_id}")
        
    print("\nInitializing Google Calendar Service...")
    service = get_calendar_service()
    if not service:
        print("[FAIL] Google Calendar Service could not be initialized. Check google_credentials.json.")
        return False
        
    print("[SUCCESS] Google Calendar client initialized successfully.")
    
    print(f"\nRetrieving details for calendar: {calendar_id}...")
    try:
        # Call the Google Calendar API to get details of the calendar
        cal_meta = service.calendars().get(calendarId=calendar_id).execute()
        print("[SUCCESS] Successfully connected to Google Calendar API!")
        print("-" * 40)
        print(f"Summary:       {cal_meta.get('summary')}")
        print(f"Timezone:      {cal_meta.get('timeZone')}")
        print(f"Description:   {cal_meta.get('description', 'No description')}")
        print("-" * 40)
        
        print("\nListing next 3 upcoming events as verification...")
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=now,
            maxResults=3,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])
        
        if not events:
            print("No upcoming events found (or calendar is empty).")
        else:
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                print(f"- {start}: {event.get('summary')} (ID: {event.get('id')[:8]}...)")
                
        print("\n[VERIFIED] Google Calendar integration is fully working and connected!")
        return True
        
    except Exception as e:
        print(f"[FAIL] Failed to communicate with Google Calendar API: {e}")
        print("Please check that the Service Account has been shared with this calendar ID with 'Make changes to events' permission.")
        return False

if __name__ == "__main__":
    test_connection()
