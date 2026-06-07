import re
import os

def verify_rules():
    print("=== Validation Tests: Formatted System Prompt Review ===")
    
    # 1. Load Shaan's resume (either resume.txt or the hardcoded fallback)
    shaan_resume = ""
    if os.path.exists("resume.txt"):
        with open("resume.txt", "r") as rf:
            shaan_resume = rf.read().strip()
            
    if not shaan_resume:
        # Load from fallback inside app.py
        with open("app.py", "r") as f:
            content = f.read()
        fallback_match = re.search(r'shaan_resume = """(.*?)"""', content, re.DOTALL)
        if fallback_match:
            shaan_resume = fallback_match.group(1)
            
    # 2. Load the system prompt template
    with open("app.py", "r") as f:
        app_content = f.read()
        
    prompt_match = re.search(r'system_prompt = f"""(.*?)"""', app_content, re.DOTALL)
    if not prompt_match:
        print("[FAIL] Could not locate system_prompt definition in app.py.")
        return
        
    prompt_template = prompt_match.group(1)
    
    # Format the prompt
    formatted_prompt = prompt_template.replace("{shaan_resume}", shaan_resume)
    
    # Validation questions to verify
    test_questions = [
        ("What is Shaan’s current role?", ["role", "analyst"]),
        ("Tell me about Carbon Crunch.", ["carbon crunch"]),
        ("Did Shaan work at Google?", ["did shaan work at google?"]),
        ("Is Shaan a Senior Software Engineer?", ["is shaan a senior software engineer?"]),
        ("Is Shaan an AI Engineer?", ["is shaan an ai engineer?"]),
        ("What skills does Shaan have?", ["skills"])
    ]
    
    passed_all = True
    print("\nVerifying Classification Rules against formatted system prompt:")
    
    # 1. Verify shortened introduction rule
    print("\nChecking shortened introduction:")
    intro_check = "Shaan is a Data Analyst and Business Analyst with experience in analytics, Python, SQL, automation, and data-driven problem solving"
    if intro_check in formatted_prompt:
        print("[PASS] Spoken introduction contains Data/Business Analyst role and core experience highlights.")
    else:
        print("[FAIL] Spoken introduction does not match the requested shorter description.")
        passed_all = False
        
    # 2. Check each question/topic validation rule
    for q, keywords in test_questions:
        matched = all(k.lower() in formatted_prompt.lower() for k in keywords)
        if matched:
            print(f"[PASS] Prompt covers: '{q}' (contains keywords: {keywords})")
        else:
            print(f"[FAIL] Prompt does not appear to cover: '{q}'")
            passed_all = False
            
    # 3. Check off-topic classification exclusion rule
    print("\nChecking off-topic classification rules:")
    classification_check = "employment history, education, internships, projects, skills, experience, companies worked for, job titles, or qualifications"
    if classification_check in formatted_prompt:
        print("[PASS] Core career classification rule explicitly added to prevent labeling negative factual background questions as off-topic.")
    else:
        print("[FAIL] Core career classification rule missing.")
        passed_all = False
        
    if passed_all:
        print("\n[SUCCESS] All system prompt guidelines and validation conditions satisfied!")
    else:
        print("\n[WARNING] Some system prompt check conditions were not met.")

if __name__ == "__main__":
    verify_rules()
