import re

def clean_transcript_text(text, correct_email):
    # Regex to catch various spelled-out email patterns
    email_spelled_pattern = re.compile(
        r'\b[a-z0-9\s_\"\'\-\(\)]*(?:@|at\s+the\s+rate\s+of|at\s+the\s+rate|at\s+rate|at)\s*[a-z0-9\s_\"\'\-\(\)]*(?:\.|dot)\s*(?:com|c\s+o\s+m|net|org|edu)\b',
        re.IGNORECASE
    )
    
    match = email_spelled_pattern.search(text)
    if match:
        matched_str = match.group(0)
        print(f"Matched raw text: '{matched_str}'")
        
        # Clean up common conversational prefixes at the start of the matched text
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
        
        cleaned_match = matched_str
        for prefix in prefixes_to_strip:
            cleaned_match = re.sub(prefix, "", cleaned_match, flags=re.IGNORECASE)
            
        print(f"Cleaned match to replace: '{cleaned_match}'")
        
        # Replace only the cleaned match in the original text
        # To avoid partial match issues, we replace the exact cleaned_match string
        return text.replace(matched_str, matched_str.replace(cleaned_match, correct_email))
    return text

# Test cases
test_cases = [
    ("Thanks for clarifying. So that is s h a a n g r e a to minus 2 0 so minus 3 at g m a I l dot c o m. Correct?", "shaanthegreat2003@gmail.com"),
    ("So that is s h a a n t h e g r e a minus 2 0 0 minus 3 at g m a I l dot c o m. Correct?", "shaanthegreat2003@gmail.com"),
    ("My email is s h a a n t h e g r e a t 2 0 0 3 at the rate g mail dot com.", "shaanthegreat2003@gmail.com"),
    ("Please send it to shaan raza 0007 at gmail.com tomorrow.", "shaanraza0007@gmail.com"),
    ("Is it s h a a n r a z a zero zero zero seven at gmail dot com?", "shaanraza0007@gmail.com")
]

for text, email in test_cases:
    print("-" * 50)
    print(f"Original: {text}")
    cleaned = clean_transcript_text(text, email)
    print(f"Cleaned:  {cleaned}")
