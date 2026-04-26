import os
import mysql.connector
from mysql.connector import pooling
import logging
from contextlib import contextmanager
from dotenv import load_dotenv
import json
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta
import hashlib

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_CONFIG = {
    "host": os.getenv("MYSQLHOST") or os.getenv("DB_HOST"),
    "user": os.getenv("MYSQLUSER") or os.getenv("DB_USER"),
    "password": os.getenv("MYSQLPASSWORD") or os.getenv("DB_PASSWORD"),
    "database": os.getenv("MYSQLDATABASE") or os.getenv("DB_NAME"),
    "port": int(os.getenv("MYSQLPORT") or os.getenv("DB_PORT", "3306")),
}

# Connection pool
try:
    cnxpool = pooling.MySQLConnectionPool(
        pool_name="universal_pool",
        pool_size=5,
        pool_reset_session=True,
        **DB_CONFIG,
    )
    logger.info("MySQL connection pool initialized successfully")
except Exception as e:
    logger.error(f"Failed to create MySQL pool: {e}")
    cnxpool = None

@contextmanager
def get_db_conn():
    conn = None
    try:
        if cnxpool:
            conn = cnxpool.get_connection()
        else:
            conn = mysql.connector.connect(**DB_CONFIG)
        yield conn
    except mysql.connector.Error as err:
        logger.error(f"MySQL Error: {err}")
        raise
    except Exception as e:
        logger.error(f"General DB error: {e}")
        raise
    finally:
        if conn and conn.is_connected():
            conn.close()

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

# ========== CLIENT FUNCTIONS ==========

def get_client_by_id(client_id: int) -> Optional[Dict]:
    try:
        with get_db_conn() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT id, company_name, email, phone, whatsapp_business_number, industry_type,
                       subscription_status, trial_ends_at, max_leads_month, leads_count_month
                FROM clients WHERE id = %s
            """, (client_id,))
            return cursor.fetchone()
    except Exception as e:
        logger.error(f"Error getting client: {e}")
        return None

def get_client_by_phone_number(phone_number: str) -> Optional[Dict]:
    try:
        with get_db_conn() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT id, company_name, industry_type, subscription_status
                FROM clients WHERE phone = %s AND subscription_status IN ('trial', 'active')
            """, (phone_number,))
            return cursor.fetchone()
    except Exception as e:
        logger.error(f"Error getting client by phone: {e}")
        return None

def get_client_by_company_name(company_name: str) -> Optional[Dict]:
    try:
        with get_db_conn() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT id, company_name, email, phone, industry_type, subscription_status
                FROM clients WHERE company_name = %s
            """, (company_name,))
            return cursor.fetchone()
    except Exception as e:
        logger.error(f"Error getting client by company name: {e}")
        return None
    
def get_client_by_whatsapp_number(whatsapp_number: str) -> Optional[Dict]:
    """
    Get client by their WhatsApp business number
    """
    try:
        with get_db_conn() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT id, company_name, email, phone, whatsapp_business_number, industry_type, subscription_status
                FROM clients WHERE whatsapp_business_number = %s
            """, (whatsapp_number,))
            return cursor.fetchone()
    except Exception as e:
        logger.error(f"Error getting client by whatsapp number: {e}")
        return None

def get_flow_config(client_id: int) -> Optional[Dict]:
    try:
        with get_db_conn() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT flow_json, confirmation_template, scoring_rules
                FROM flow_configs WHERE client_id = %s
            """, (client_id,))
            result = cursor.fetchone()
            if result and result['flow_json']:
                return json.loads(result['flow_json'])
            return None
    except Exception as e:
        logger.error(f"Error getting flow config: {e}")
        return None

# ========== SESSION FUNCTIONS ==========

def get_user_session(phone: str) -> Dict:
    try:
        with get_db_conn() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT phone, client_id, current_step, responses_so_far
                FROM conversation_sessions WHERE phone = %s
            """, (phone,))
            result = cursor.fetchone()
            if result:
                return {
                    'phone': result['phone'],
                    'client_id': result['client_id'],
                    'current_step': result['current_step'],
                    'responses': json.loads(result['responses_so_far']) if result['responses_so_far'] else {}
                }
    except Exception as e:
        logger.error(f"Error getting session: {e}")
    
    return {
        'phone': phone,
        'client_id': None,
        'current_step': 'welcome',
        'responses': {}
    }

def update_user_session(phone: str, updates: Dict):
    try:
        with get_db_conn() as conn:
            cursor = conn.cursor()
            
            # Check if session exists
            cursor.execute("SELECT phone FROM conversation_sessions WHERE phone = %s", (phone,))
            exists = cursor.fetchone()
            
            current_step = updates.get('current_step', 'welcome')
            responses = json.dumps(updates.get('responses', {}))
            client_id = updates.get('client_id')
            
            if exists:
                cursor.execute("""
                    UPDATE conversation_sessions 
                    SET client_id = %s, current_step = %s, responses_so_far = %s
                    WHERE phone = %s
                """, (client_id, current_step, responses, phone))
            else:
                cursor.execute("""
                    INSERT INTO conversation_sessions (phone, client_id, current_step, responses_so_far)
                    VALUES (%s, %s, %s, %s)
                """, (phone, client_id, current_step, responses))
            
            conn.commit()
    except Exception as e:
        logger.error(f"Error updating session: {e}")

def clear_user_session(phone: str):
    try:
        with get_db_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM conversation_sessions WHERE phone = %s", (phone,))
            conn.commit()
    except Exception as e:
        logger.error(f"Error clearing session: {e}")

# ========== LEAD FUNCTIONS ==========

def create_lead(client_id: int, name: str, phone: str, lead_data: Dict, lead_score: int = 0) -> int:
    try:
        with get_db_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO leads (client_id, name, phone, lead_data, lead_score, status)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (client_id, name, phone, json.dumps(lead_data), lead_score, 'new'))
            conn.commit()
            lead_id = cursor.lastrowid
            
            # Update client lead count
            cursor.execute("""
                UPDATE clients SET leads_count_month = leads_count_month + 1
                WHERE id = %s
            """, (client_id,))
            conn.commit()
            
            return lead_id
    except Exception as e:
        logger.error(f"Error creating lead: {e}")
        return 0

def check_client_lead_limit(client_id: int) -> bool:
    try:
        with get_db_conn() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT leads_count_month, max_leads_month, subscription_status, trial_ends_at
                FROM clients WHERE id = %s
            """, (client_id,))
            client = cursor.fetchone()
            
            if not client:
                return False
            
            if client['subscription_status'] not in ['trial', 'active']:
                return False
            
            if client['subscription_status'] == 'trial' and client['trial_ends_at']:
                if datetime.now() > client['trial_ends_at']:
                    return False
            
            if client['leads_count_month'] >= client['max_leads_month']:
                return False
            
            return True
    except Exception as e:
        logger.error(f"Error checking lead limit: {e}")
        return False

# ========== ERROR LOGGING ==========

def log_error(phone: str = None, client_id: int = None, error_message: str = ""):
    try:
        with get_db_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO error_logs (phone, client_id, error_message)
                VALUES (%s, %s, %s)
            """, (phone, client_id, error_message))
            conn.commit()
    except Exception as e:
        logger.error(f"Error logging error: {e}")

# ========== ADMIN FUNCTIONS ==========

def get_leads_by_client(client_id: int, limit: int = 100) -> List[Dict]:
    try:
        with get_db_conn() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT * FROM leads WHERE client_id = %s ORDER BY created_at DESC LIMIT %s
            """, (client_id, limit))
            return cursor.fetchall()
    except Exception as e:
        logger.error(f"Error getting leads: {e}")
        return []

def get_all_leads(limit: int = 1000) -> List[Dict]:
    try:
        with get_db_conn() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT l.*, c.company_name as client_name
                FROM leads l
                LEFT JOIN clients c ON l.client_id = c.id
                ORDER BY l.created_at DESC LIMIT %s
            """, (limit,))
            return cursor.fetchall()
    except Exception as e:
        logger.error(f"Error getting all leads: {e}")
        return []

def verify_client_login(email: str, password: str) -> Optional[Dict]:
    try:
        with get_db_conn() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT id, company_name, email, password_hash, industry_type
                FROM clients WHERE email = %s
            """, (email,))
            client = cursor.fetchone()
            
            if client and client['password_hash'] == hash_password(password):
                return client
            return None
    except Exception as e:
        logger.error(f"Error verifying login: {e}")
        return None