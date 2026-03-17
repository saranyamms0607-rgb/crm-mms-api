import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

def debug_env():
    # Force reload from .env
    env_path = BASE_DIR / ".env"
    print(f"Loading env from: {env_path}")
    print(f"File exists: {env_path.exists()}")
    
    # Read file manually to see what's in it (sanitized)
    print("\nManual File Read (Sanitized):")
    try:
        with open(env_path, 'r') as f:
            for line in f:
                if 'EMAIL' in line or 'DEFAULT_FROM' in line:
                    key = line.split('=')[0]
                    value = line.split('=')[1].strip() if '=' in line else ''
                    hidden_val = value[:3] + "..." + value[-3:] if len(value) > 6 else "short"
                    print(f"{key}={hidden_val}")
    except Exception as e:
        print(f"Error reading file: {e}")

    load_dotenv(env_path, override=True)
    
    print("\nos.environ Values (Sanitized):")
    keys = ["EMAIL_HOST", "EMAIL_PORT", "EMAIL_HOST_USER", "EMAIL_HOST_PASSWORD", "DEFAULT_FROM_EMAIL"]
    for k in keys:
        v = os.environ.get(k, "NOT SET")
        hidden_v = v[:3] + "..." + v[-3:] if len(v) > 6 else v
        print(f"{k}: {hidden_v}")

if __name__ == '__main__':
    debug_env()
