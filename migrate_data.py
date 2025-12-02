import json
import os
from supabase import create_client, Client

# --- CONFIGURATION ---

SUPABASE_URL = 'https://iqqczpmvqiuqrtnzusqx.supabase.co'
SUPABASE_KEY = "sb_publishable_7EhrzbtM43LQrNFCY019UQ_KKKjCino"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def migrate():
    print("Starting migration...")

    # 1. Migrate Services
    if os.path.exists('data/services.json'):
        with open('data/services.json', 'r') as f:
            services_data = json.load(f)
        
        # We store services in the 'settings' table with key='services'
        # This is cleaner than a separate table for a single object
        supabase.table('settings').upsert({
            'key': 'services',
            'value': services_data
        }).execute()
        print("✅ Services migrated.")
    else:
        print("⚠️ data/services.json not found.")

    # 2. Migrate Company Settings
    if os.path.exists('data/company_settings.json'):
        with open('data/company_settings.json', 'r') as f:
            settings_data = json.load(f)
        
        supabase.table('settings').upsert({
            'key': 'company_settings',
            'value': settings_data
        }).execute()
        print("✅ Company settings migrated.")
    else:
        print("⚠️ data/company_settings.json not found.")

    # 3. Migrate Job Summary
    # We wrap the text in a JSON object because the column is JSONB
    if os.path.exists('data/job_summary.txt'):
        with open('data/job_summary.txt', 'r') as f:
            summary_text = f.read()
        
        supabase.table('settings').upsert({
            'key': 'job_summary',
            'value': {"text": summary_text}
        }).execute()
        print("✅ Job summary migrated.")
    else:
        print("⚠️ data/job_summary.txt not found.")

if __name__ == "__main__":
    migrate()