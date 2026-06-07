import requests
import json
import time
import datetime

BASE_URL = "http://127.0.0.1:8080"

def run_tests():
    print("--- 1. Testing calendar dynamics ---")
    res = requests.get(f"{BASE_URL}/api/calendar")
    slots = res.json()
    print(f"Total calendar slots fetched: {len(slots)}")
    
    # Check what dates we have
    dates = sorted(list(set(s["date"] for s in slots)))
    print("Dates in calendar:", dates)
    
    # Check if Saturday, June 6 is present, and if it is, make sure its status is 'past'
    jun_6_slots = [s for s in slots if s["date"] == "2026-06-06"]
    if jun_6_slots:
        print(f"Found {len(jun_6_slots)} slots on 2026-06-06. Statuses: {[s['status'] for s in jun_6_slots]}")
        for s in jun_6_slots:
            if s["status"] != "past":
                print("FAIL: Slot on 2026-06-06 is not marked as past!")
            else:
                print("PASS: Slot on 2026-06-06 is correctly marked as past")
    else:
        print("2026-06-06 not found in slots (which is correct if slots started from a newer date)")

    # Find a future slot to book
    future_slot = None
    for s in slots:
        if s["status"] == "available":
            future_slot = s
            break
            
    if not future_slot:
        print("FAIL: No future available slot found in the calendar.")
        return
        
    print(f"Selected future slot for test booking: Date={future_slot['date']}, Time={future_slot['time']}")

    print("\n--- 2. Testing webhook booking with messy spoken email and phone ---")
    mock_call_id = f"test-spoken-normalization-{int(time.time())}"
    mock_payload = {
        "message": {
            "type": "tool-calls",
            "toolCalls": [
                {
                    "id": "call-tool-999",
                    "function": {
                        "name": "book_interview_slot",
                        "arguments": {
                            "interviewer_name": "Spoken Recruiter",
                            "interviewer_email": "shaan raza 0007 at gmail dot com",
                            "interviewer_phone": "one six six two six five seven eight six seven four",
                            "date": future_slot["date"],
                            "time": future_slot["time"]
                        }
                    }
                }
            ],
            "call": {
                "id": mock_call_id
            }
        }
    }
    
    res = requests.post(f"{BASE_URL}/api/webhook", json=mock_payload)
    print("Booking Webhook Status Code:", res.status_code)
    booking_result = res.json()
    print("Booking Webhook Response:", json.dumps(booking_result, indent=2))
    
    # Retrieve the lead details and verify normalization
    print("\n--- 3. Verifying normalization in contacts store ---")
    res = requests.get(f"{BASE_URL}/api/contacts")
    contacts = res.json()
    booked_lead = None
    for c in contacts:
        if c.get("call_id") == mock_call_id:
            booked_lead = c
            break
            
    if booked_lead:
        print("Found booked lead!")
        print(f"Captured Name:  {booked_lead.get('name')}")
        print(f"Captured Email: {booked_lead.get('email')}")
        print(f"Captured Phone: {booked_lead.get('phone')}")
        
        email_ok = booked_lead.get('email') == "shaanraza0007@gmail.com"
        phone_ok = booked_lead.get('phone') == "16626578674" or booked_lead.get('phone') == "+16626578674"
        
        if email_ok and phone_ok:
            print("PASS: Spoken email and phone were successfully normalized!")
        else:
            if not email_ok:
                print("FAIL: Email not normalized correctly.")
            if not phone_ok:
                print("FAIL: Phone not normalized correctly.")
    else:
        print("FAIL: Booked lead not found in contacts store.")

if __name__ == "__main__":
    run_tests()
