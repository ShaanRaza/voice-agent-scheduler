import os

file_path = "static/app.js"
with open(file_path, "rb") as f:
    content = f.read()

# Replace the corrupted block in the autofill section
corrupted_autofill_bytes = b"publicKeyInput.placeholder = '\xe2\x80\xa2\xef\xbf\xbd        if (!phoneNumberInput.value && status.phone_number) {"
clean_autofill_bytes = b"publicKeyInput.placeholder = '\xe2\x80\xa2\xe2\x80\xa2\xe2\x80\xa2\xe2\x80\xa2\xe2\x80\xa2\xe2\x80\xa2\xe2\x80\xa2\xe2\x80\xa2\xe2\x80\xa2\xe2\x80\xa2\xe2\x80\xa2\xe2\x80\xa2\xe2\x80\xa2\xe2\x80\xa2\xe2\x80\xa2\xe2\x80\xa2 (Saved)';\n        }\n        if (!phoneNumberInput.value && status.phone_number) {"

if corrupted_autofill_bytes in content:
    content = content.replace(corrupted_autofill_bytes, clean_autofill_bytes)
    print("Repaired autofill section!")
else:
    # Let's do a fallback replacement using string decode
    try:
        text = content.decode("utf-8", errors="ignore")
        if "publicKeyInput.placeholder = '•" in text:
            # find where it starts and ends
            idx = text.find("publicKeyInput.placeholder = '•")
            # We will replace from "publicKeyInput.placeholder = '•" until "if (!phoneNumberInput.value && status.phone_number) {"
            end_idx = text.find("if (!phoneNumberInput.value && status.phone_number) {", idx)
            if idx != -1 and end_idx != -1:
                target_block = text[idx:end_idx]
                text = text.replace(target_block, "publicKeyInput.placeholder = '•••••••••••••••• (Saved)';\n        }\n        ")
                content = text.encode("utf-8")
                print("Repaired autofill section via text mode!")
    except Exception as e:
        print("Error in fallback autofill repair:", e)

# Replace the duplicated error handling in saveConfig
corrupted_save_config_bytes = b"btnSaveConfig.disabled = false;\n    }\n}alert('Failed to save config.');\n    } finally {\n        btnSaveConfig.disabled = false;\n    }\n}"
clean_save_config_bytes = b"btnSaveConfig.disabled = false;\n    }\n}"

if corrupted_save_config_bytes in content:
    content = content.replace(corrupted_save_config_bytes, clean_save_config_bytes)
    print("Repaired saveConfig error handler!")
else:
    try:
        text = content.decode("utf-8", errors="ignore")
        bad_str = "}alert('Failed to save config.');\n    } finally {\n        btnSaveConfig.disabled = false;\n    }\n}"
        if bad_str in text:
            text = text.replace(bad_str, "}")
            content = text.encode("utf-8")
            print("Repaired saveConfig error handler via text mode!")
    except Exception as e:
        print("Error in fallback saveConfig repair:", e)

with open(file_path, "wb") as f:
    f.write(content)
print("File static/app.js written successfully.")
