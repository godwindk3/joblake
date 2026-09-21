"""Compatibility entry point for verification of the active serving replica."""
from dotenv import load_dotenv
from joblake.supabase_sync import sync

if __name__ == "__main__":
    load_dotenv()
    raise SystemExit(sync(verify_only=True))
