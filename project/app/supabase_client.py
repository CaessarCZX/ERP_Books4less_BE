from supabase import create_client
from config.config import Config  # porque está en project/config/config.py

supabase = create_client(Config.SUPABASE_URL, Config.SUPABASE_API_KEY)
