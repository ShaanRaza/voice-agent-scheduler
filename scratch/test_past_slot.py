import requests
import json

BASE_URL = "http://127.0.0.1:8080"

def test_past_slot():
    print("Testing booking a past slot via mock webhook...")
    
    # Slot date is Saturday June 6, 2026 (which is in the past, today is Sunday June 7, 2026)
    mock_payload = {
        "message": {
            "type": "tool-calls",
            "toolCalls": [
                {
                    "id": "call-tool-past",
                    "function": {
                        "name": "book_interview_slot",
                        "arguments": {
                            "interviewer_name": "Past Recruiter",
                            "interviewer_email": "recruiter@past.com",
                            "interviewer_phone": "+1-123-456-7890",
                            "date": "2026-06-06",
                            "time": "11:00 AM"
                        }
                    }
                }
            ],
            "call": {
                "id": "mock-call-id-past"
            }
        }
    }
    
    try:
        res = requests.post(f"{BASE_URL}/api/webhook", json=mock_payload)
        print("Status Code:", res.status_code)
        response_json = res.json()
        print("Response JSON:")
        print(json.dumps(response_json, indent=2))
        
        result_msg = response_json["results"][0]["result"]
        if "Error: The slot on 2026-06-06 at 11:00 AM has already passed" in result_msg:
            print("PASS: Correctly rejected past slot booking!")
        else:
            print("FAIL: Did not reject or returned unexpected message:", result_msg)
            
    except Exception as e:
        print("FAIL: Request failed:", e)

if __name__ == "__main__":
    test_past_slot()
