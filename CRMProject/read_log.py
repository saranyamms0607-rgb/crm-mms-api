
import os

log_path = 'server_log.txt'
if os.path.exists(log_path):
    with open(log_path, 'rb') as f:
        content = f.read()
    
    # Try different encodings
    encodings = ['utf-8', 'utf-16', 'utf-16-le', 'utf-16-be', 'latin-1']
    for enc in encodings:
        try:
            text = content.decode(enc)
            print(f"--- SUCCESS with {enc} ---")
            print(text[-2000:]) # Last 2000 characters
            break
        except Exception:
            continue
else:
    print("File not found")
