import requests
import json
import time

BASE_URL = "http://127.0.0.1:8080"

def run_tests():
    print("1. Testing GET /api/status...")
    try:
        res = requests.get(f"{BASE_URL}/api/status")
        print("Status Code:", res.status_code)
        print("Response:", res.json())
    except Exception as e:
        print("Failed:", e)
        return

    print("\n2. Testing GET /api/contacts...")
    try:
        res = requests.get(f"{BASE_URL}/api/contacts")
        print("Status Code:", res.status_code)
        contacts = res.json()
        print("Contacts count:", len(contacts))
    except Exception as e:
        print("Failed:", e)
        return

    # Trigger a mock booking tool-call to create a lead
    print("\n3. Testing Mock tool-call to book a slot...")
    mock_payload = {
        "message": {
            "type": "tool-calls",
            "toolCalls": [
                {
                    "id": "call-tool-123",
                    "function": {
                        "name": "book_interview_slot",
                        "arguments": {
                            "interviewer_name": "Test Recruiter",
                            "interviewer_email": "recruiter@test.com",
                            "interviewer_phone": "+1-123-456-7890",
                            "date": "2026-06-08",
                            "time": "11:00 AM"
                        }
                    }
                }
            ],
            "call": {
                "id": "mock-call-id-999"
            }
        }
    }
    
    try:
        res = requests.post(f"{BASE_URL}/api/webhook", json=mock_payload)
        print("Webhook Status Code:", res.status_code)
        print("Webhook Response:", res.json())
    except Exception as e:
        print("Failed webhook tool-call:", e)

    # Let's fetch contacts to find our new lead
    print("\n4. Retrieving lead from database...")
    try:
        res = requests.get(f"{BASE_URL}/api/contacts")
        contacts = res.json()
        target_contact = None
        for c in contacts:
            if c.get("call_id") == "mock-call-id-999":
                target_contact = c
                break
        
        if target_contact:
            print("Successfully found contact with call_id!")
            print("Contact Details:", json.dumps(target_contact, indent=2))
            
            # Update status and notes
            contact_id = target_contact["id"]
            print(f"\n5. Updating contact {contact_id} status & notes via PUT...")
            update_payload = {
                "status": "Technical Round",
                "notes": "Met recruiter at the mock call session. Very positive."
            }
            res_put = requests.put(f"{BASE_URL}/api/contacts/{contact_id}", json=update_payload)
            print("PUT Status Code:", res_put.status_code)
            print("PUT Response:", res_put.json())
            
            # Fetch again to verify update
            res_get = requests.get(f"{BASE_URL}/api/contacts")
            for updated_c in res_get.json():
                if updated_c["id"] == contact_id:
                    print("Updated Contact Details:", json.dumps(updated_c, indent=2))
        else:
            print("Target contact not found in list:", contacts)
    except Exception as e:
        print("Failed contact operations:", e)

    # Trigger mock end-of-call-report webhook
    print("\n6. Testing end-of-call-report webhook...")
    # Add a mock transcript to logs first so the heuristic analyzer can parse it
    # We can simulate this by sending conversation-update message
    conversation_payload = {
        "message": {
            "type": "conversation-update",
            "conversation": [
                {"role": "assistant", "text": "Hi, I am Shaan's AI representative. Let's schedule an interview."},
                {"role": "user", "text": "Great! What experience does Shaan have with React and Python?"},
                {"role": "assistant", "text": "Shaan has 5+ years of experience with React, Python, and Flask."},
                {"role": "user", "text": "Excellent. Can we schedule for next Monday at 10 AM?"}
            ],
            "call": {
                "id": "mock-call-id-999"
            }
        }
    }
    try:
        res_conv = requests.post(f"{BASE_URL}/api/webhook", json=conversation_payload)
        print("Conv update status:", res_conv.status_code)
    except Exception as e:
        print("Failed conv update:", e)

    end_call_payload = {
        "message": {
            "type": "end-of-call-report",
            "recordingUrl": "https://example.com/recording.mp3",
            "summary": "Mock summary: Recruiter asked about Python/React experience and booked slots.",
            "call": {
                "id": "mock-call-id-999"
            }
        }
    }
    
    try:
        res_end = requests.post(f"{BASE_URL}/api/webhook", json=end_call_payload)
        print("End call webhook status:", res_end.status_code)
        
        # Wait a moment for background post-call thread
        print("Waiting 3 seconds for background post-call processing...")
        time.sleep(3)
        
        # Check contact details
        res_contacts = requests.get(f"{BASE_URL}/api/contacts")
        for c in res_contacts.json():
            if c.get("call_id") == "mock-call-id-999":
                print("Final Contact Details after Post-Call Analysis:")
                print(json.dumps(c, indent=2))
    except Exception as e:
        print("Failed end-of-call webhook:", e)

if __name__ == "__main__":
    run_tests()
