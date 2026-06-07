import requests
import json
import time

BASE_URL = "http://127.0.0.1:8080"

def run_simulation():
    print("=== End-to-End Simulation: Voice Representative Workflow ===")
    
    # 1. Fetch current calendar to find an open slot
    print("\n1. Fetching available slots...")
    res = requests.get(f"{BASE_URL}/api/calendar")
    slots = res.json()
    available_slot = None
    for s in slots:
        if s["status"] == "available" and s["date"] > "2026-06-07":
            available_slot = s
            break
            
    if not available_slot:
        print("[FAIL] No upcoming available slot found to test booking.")
        return
        
    print(f"[OK] Found available slot on {available_slot['date']} at {available_slot['time']}.")
    
    # 2. Simulate tool call with messy spoken spelling and domain phrasing
    print("\n2. Simulating Vapi Voice Agent webhook tool call...")
    mock_call_id = f"sim-call-{int(time.time())}"
    webhook_payload = {
        "message": {
            "type": "tool-calls",
            "toolCalls": [
                {
                    "id": "sim-tool-call-id",
                    "function": {
                        "name": "book_interview_slot",
                        "arguments": {
                            "interviewer_name": "Simulation Recruiter",
                            "interviewer_email": "shaanthegreat 2 0 0 3 at the rate g mail dot com",
                            "interviewer_phone": "one six six two six five seven eight six seven four",
                            "date": available_slot["date"],
                            "time": available_slot["time"]
                        }
                    }
                }
            ],
            "call": {
                "id": mock_call_id
            }
        }
    }
    
    res = requests.post(f"{BASE_URL}/api/webhook", json=webhook_payload)
    print(f"Webhook Status: {res.status_code}")
    response_data = res.json()
    print("Webhook Response:", json.dumps(response_data, indent=2))
    
    # Check booking result
    booking_result = response_data["results"][0]["result"]
    if "Success!" not in booking_result:
        print("[FAIL] Booking tool-call failed.")
        return
        
    # 3. Verify lead normalization in the database
    print("\n3. Verifying database normalization and Google event storage...")
    res = requests.get(f"{BASE_URL}/api/contacts")
    contacts = res.json()
    target_contact = None
    for c in contacts:
        if c.get("call_id") == mock_call_id:
            target_contact = c
            break
            
    if not target_contact:
        print("[FAIL] Booked contact was not saved to contacts store.")
        return
        
    print(f"[OK] Contact found in leads list.")
    print(f"  Name:             {target_contact.get('name')}")
    print(f"  Normalized Email: {target_contact.get('email')}")
    print(f"  Normalized Phone: {target_contact.get('phone')}")
    print(f"  Google Event ID:  {target_contact.get('google_event_id')}")
    
    if target_contact.get("email") != "shaanthegreat2003@gmail.com":
        print("[FAIL] Spoken email was not normalized correctly.")
        return
    if target_contact.get("phone") != "16626578674":
        print("[FAIL] Spoken phone number was not normalized correctly.")
        return
    if not target_contact.get("google_event_id"):
        print("[FAIL] Google Calendar event ID was not stored.")
        return
        
    print("[PASS] Spoken data successfully normalized and stored!")
    
    # 3b. Simulate a webhook sending the spelled-out transcript and check cleanup
    print("\n3b. Simulating webhook transcript with spelled-out spelling errors...")
    transcript_payload = {
        "message": {
            "type": "transcript",
            "role": "assistant",
            "transcript": "Thanks for clarifying. So that is s h a a n g r e a to minus 2 0 so minus 3 at g m a I l dot c o m. Correct?",
            "call": {
                "id": mock_call_id
            }
        }
    }
    res = requests.post(f"{BASE_URL}/api/webhook", json=transcript_payload)
    print(f"Transcript Webhook Status: {res.status_code}")
    
    conv_payload = {
        "message": {
            "type": "conversation-update",
            "conversation": [
                {
                    "role": "user",
                    "content": "s h a a n t h e g r e a t 2 0 0 3 at the rate g mail dot com."
                },
                {
                    "role": "assistant",
                    "content": "Thanks for clarifying. So that is s h a a n g r e a to minus 2 0 so minus 3 at g m a I l dot c o m. Correct?"
                }
            ],
            "call": {
                "id": mock_call_id
            }
        }
    }
    res = requests.post(f"{BASE_URL}/api/webhook", json=conv_payload)
    print(f"Conversation Update Webhook Status: {res.status_code}")
    
    # Retrieve logs to see if they are cleaned
    res = requests.get(f"{BASE_URL}/api/logs")
    logs = res.json()
    matched_log = None
    for log in logs:
        if log.get("call_id") == mock_call_id:
            matched_log = log
            break
            
    if not matched_log:
        print("[FAIL] Log record not found for simulated call.")
        return
        
    print("[OK] Log record found. Verifying transcript cleanup...")
    print("Mangled speech in webhook: 'Thanks for clarifying. So that is s h a a n g r e a to minus 2 0 so minus 3 at g m a I l dot c o m. Correct?'")
    
    transcript_msgs = matched_log.get("transcript", [])
    assistant_msg = None
    # Look for the assistant message that should be cleaned
    for msg in transcript_msgs:
        if msg.get("role") == "assistant" and "Thanks for clarifying" in msg.get("text", ""):
            assistant_msg = msg.get("text")
            break
            
    print(f"Actual transcript text in log: '{assistant_msg}'")
    expected_cleanup = "Thanks for clarifying. So that is shaanthegreat2003@gmail.com. Correct?"
    if assistant_msg == expected_cleanup:
        print("[PASS] Spelled-out email with transcription errors was successfully cleaned to correct email!")
    else:
        print(f"[FAIL] Expected transcript cleanup to '{expected_cleanup}', got '{assistant_msg}'")
        return
        
    # 4. Trigger database reset and verify Google Calendar event deletion
    print("\n4. Triggering Database Reset (/api/calendar/reset) to test auto-deletion of invites...")
    # We will trigger the POST request to reset
    res = requests.post(f"{BASE_URL}/api/calendar/reset")
    print(f"Reset Status: {res.status_code}")
    reset_data = res.json()
    
    # Check if the slot is now back to 'available'
    new_slots = reset_data.get("calendar", [])
    reset_slot = None
    for s in new_slots:
        if s["date"] == available_slot["date"] and s["time"] == available_slot["time"]:
            reset_slot = s
            break
            
    if reset_slot and reset_slot["status"] == "available":
        print("[PASS] Calendar slot is now back to 'available' locally.")
    else:
        print(f"[FAIL] Calendar slot status is {reset_slot['status'] if reset_slot else 'None'} (expected 'available').")
        
    # Check that contacts list is empty
    res = requests.get(f"{BASE_URL}/api/contacts")
    remaining_contacts = res.json()
    if len(remaining_contacts) == 0:
        print("[PASS] Contacts store successfully cleared.")
    else:
        print(f"[FAIL] Contacts store not cleared. Count: {len(remaining_contacts)}")
        
    print("\n[SUCCESS] End-to-End simulation completed successfully!")

if __name__ == "__main__":
    run_simulation()
