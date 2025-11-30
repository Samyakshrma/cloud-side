# database.py
import os
import psycopg2
from datetime import datetime
from typing import Dict
from dotenv import load_dotenv

# --- Load environment variables ---
load_dotenv()

# --- Configuration ---
CONN_STRING = os.getenv("NEON_CONN_STRING")
if not CONN_STRING:
    raise ValueError("NEON_CONN_STRING is missing in .env")

TABLE_INCIDENTS = "validated_incidents"
TABLE_STATS = "verification_stats"
TABLE_HEARTBEATS = "heartbeat_stats"

# ---------------------------------------------------------------------
# DB CONNECTION
# ---------------------------------------------------------------------
def get_db_connection():
    try:
        conn = psycopg2.connect(CONN_STRING)
        return conn
    except Exception as e:
        print(f"FATAL ERROR: Could not connect to PostgreSQL:\n{e}")
        return None


# ---------------------------------------------------------------------
# INITIALIZE DATABASE
# ---------------------------------------------------------------------
def initialize_database():
    print(f"LOG: Initializing PostgreSQL tables...")
    conn = get_db_connection()
    if not conn: 
        return

    try:
        cursor = conn.cursor()

        # Incidents
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_INCIDENTS} (
                image_name TEXT PRIMARY KEY,
                alert_type TEXT NOT NULL,
                face_count_dnn INTEGER NOT NULL,
                validation_time TIMESTAMP WITH TIME ZONE NOT NULL
            );
        """)

        # Verification Stats
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_STATS} (
                id SERIAL PRIMARY KEY,
                alert_type TEXT NOT NULL,
                is_validated BOOLEAN NOT NULL,
                is_false_positive BOOLEAN NOT NULL,
                verification_time TIMESTAMP WITH TIME ZONE NOT NULL
            );
        """)

        # Heartbeats (efficiency stats)
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_HEARTBEATS} (
                id SERIAL PRIMARY KEY,
                device_id TEXT NOT NULL,
                timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                duration_seconds FLOAT NOT NULL,
                frames_processed INTEGER NOT NULL,
                frames_discarded INTEGER NOT NULL,
                local_incidents INTEGER NOT NULL
            );
        """)

        conn.commit()
        print(f"LOG: Tables Ready")
    except Exception as e:
        print(f"FATAL ERROR (init): {e}")
    finally:
        conn.close()


# ---------------------------------------------------------------------
# INSERT INCIDENT
# ---------------------------------------------------------------------
def insert_validated_incident(image_name, alert_type, face_count):
    conn = get_db_connection()
    if not conn: 
        return

    try:
        cursor = conn.cursor()
        cursor.execute(f"""
            INSERT INTO {TABLE_INCIDENTS} (image_name, alert_type, face_count_dnn, validation_time)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (image_name) DO NOTHING;
        """, (image_name, alert_type, face_count, datetime.now()))
        conn.commit()
    except Exception as e:
        print(f"DB Error (incident): {e}")
    finally:
        conn.close()


# ---------------------------------------------------------------------
# LOG VERIFICATION METRIC
# ---------------------------------------------------------------------
def log_verification_metric(alert_type, status):
    conn = get_db_connection()
    if not conn: 
        return

    try:
        cursor = conn.cursor()
        is_val = status == "VALIDATED"
        is_fp = status == "FALSE_POSITIVE"

        if is_val or is_fp:
            cursor.execute(f"""
                INSERT INTO {TABLE_STATS} (alert_type, is_validated, is_false_positive, verification_time)
                VALUES (%s, %s, %s, %s);
            """, (alert_type, is_val, is_fp, datetime.now()))
            conn.commit()
    except Exception as e:
        print(f"DB Error (verification): {e}")
    finally:
        conn.close()


# ---------------------------------------------------------------------
# LOG HEARTBEAT
# ---------------------------------------------------------------------
def log_heartbeat(device_id: str, duration: float, processed: int, discarded: int, incidents: int):
    conn = get_db_connection()
    if not conn: 
        return

    try:
        cursor = conn.cursor()
        cursor.execute(f"""
            INSERT INTO {TABLE_HEARTBEATS}
            (device_id, timestamp, duration_seconds, frames_processed, frames_discarded, local_incidents)
            VALUES (%s, %s, %s, %s, %s, %s);
        """, (device_id, datetime.now(), duration, processed, discarded, incidents))

        conn.commit()
    except Exception as e:
        print(f"DB Error (heartbeat): {e}")
    finally:
        conn.close()


# ---------------------------------------------------------------------
# GET + CLEAR STATS
# ---------------------------------------------------------------------
def get_and_clear_all_stats() -> Dict:
    conn = get_db_connection()
    if not conn:
        return {}

    data = {
        "verification_stats": {},
        "efficiency_stats": {}
    }

    try:
        cursor = conn.cursor()

        # Verification stats aggregated
        cursor.execute(f"""
            SELECT alert_type,
                   COUNT(*) AS total,
                   SUM(CASE WHEN is_validated THEN 1 ELSE 0 END) AS validated,
                   SUM(CASE WHEN is_false_positive THEN 1 ELSE 0 END) AS false_positive
            FROM {TABLE_STATS}
            GROUP BY alert_type;
        """)
        for row in cursor.fetchall():
            data["verification_stats"][row[0]] = {
                "total": row[1],
                "validated": row[2],
                "false_positive": row[3],
            }

        # Heartbeat aggregation
        cursor.execute(f"""
            SELECT 
                SUM(frames_processed),
                SUM(frames_discarded),
                SUM(local_incidents)
            FROM {TABLE_HEARTBEATS};
        """)
        hb = cursor.fetchone()

        if hb and hb[0]:
            processed, discarded, incidents = hb
            data["efficiency_stats"] = {
                "total_frames_processed": processed,
                "total_frames_discarded": discarded,
                "local_incidents_triggered": incidents,
                "bandwidth_saved_percent":
                    round((discarded / processed) * 100, 2) if processed > 0 else 0
            }
        else:
            data["efficiency_stats"] = {
                "total_frames_processed": 0,
                "bandwidth_saved_percent": 0
            }

        # Clear tables
        cursor.execute(f"DELETE FROM {TABLE_STATS}")
        cursor.execute(f"DELETE FROM {TABLE_HEARTBEATS}")

        conn.commit()

    except Exception as e:
        print(f"DB Error (get stats): {e}")
        conn.rollback()
    finally:
        conn.close()

    return data


# ---------------------------------------------------------------------
# AUTO-INIT
# ---------------------------------------------------------------------
initialize_database()
