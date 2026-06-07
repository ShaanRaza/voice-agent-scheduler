import re

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

# Test suite
tests = [
    ("shaan raza 0007 at gmail dot com", "shaanraza0007@gmail.com"),
    ("shaanraza at g male dot com", "shaanraza@gmail.com"),
    ("john dot doe underscore one two at yahoo dot com", "john.doe_12@yahoo.com"),
    ("alex dash smith ninety nine at hotmail dot com", "alex-smith99@hotmail.com"),
    ("some.name@gmail.com", "some.name@gmail.com"),
    ("  +1-662-657-8674  ", "+16626578674"),
    ("one six six two six five seven eight six seven four", "16626578674"),
    ("shaanthegreat 2 0 0 3 at the rate g mail dot com", "shaanthegreat2003@gmail.com"),
    ("none", "NA")
]

all_passed = True
for raw, expected in tests:
    if "@" in raw or "com" in raw or raw == "none":
        res = normalize_email(raw) if raw != "none" else normalize_phone(raw)
    else:
        res = normalize_phone(raw)
    
    if res != expected:
        print(f"FAIL: Input {repr(raw)} -> Got {repr(res)}, Expected {repr(expected)}")
        all_passed = False
    else:
        print(f"PASS: Input {repr(raw)} -> {repr(res)}")

if all_passed:
    print("ALL TESTS PASSED!")
else:
    print("SOME TESTS FAILED!")
