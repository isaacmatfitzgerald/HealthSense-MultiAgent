import os
import uuid

import pymysql
import pymysql.cursors


def _reader_connection():
    return pymysql.connect(
        host=os.environ["MYSQL_READER_HOST"],
        port=int(os.environ["MYSQL_READER_PORT"]),
        user=os.environ["MYSQL_READER_USER"],
        password=os.environ["MYSQL_READER_PASSWORD"],
        database=os.environ["MYSQL_READER_DATABASE"],
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def _writer_connection():
    return pymysql.connect(
        host=os.environ["MYSQL_WRITER_HOST"],
        port=int(os.environ["MYSQL_WRITER_PORT"]),
        user=os.environ["MYSQL_WRITER_USER"],
        password=os.environ["MYSQL_WRITER_PASSWORD"],
        database=os.environ["MYSQL_WRITER_DATABASE"],
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def fetch_doctor_and_slot(doctor_id: str, slot_id: str) -> dict | None:
    """Read-only lookup (agent_reader) for guard/confirmation. None if either doesn't exist or doesn't match."""
    conn = _reader_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT full_name FROM doctors WHERE doctor_id = %s", (doctor_id,))
            doctor = cur.fetchone()
            cur.execute(
                "SELECT date, time_slot, is_available, appointment_type, consultation_mode "
                "FROM doctoravailability WHERE slot_id = %s AND doctor_id = %s",
                (slot_id, doctor_id),
            )
            slot = cur.fetchone()
    finally:
        conn.close()
    if not doctor or not slot:
        return None
    return {"doctor_name": doctor["full_name"], **slot}


def discover_doctors(city: str, state: str, specialty: str, limit: int = 5) -> list[dict]:
    """Read-only discovery query (agent_reader): doctors at hospitals in the given city/state with the given specialty."""
    conn = _reader_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT d.doctor_id, d.full_name, d.primary_specialty, d.consultation_fee,
                       h.hospital_name, h.city, h.state
                FROM doctors d
                JOIN hospitals_master h ON d.hospital_id = h.hospital_id
                JOIN primary_specialty p ON d.primary_specialty = p.specialty_code
                WHERE LOWER(h.city) = LOWER(%s)
                  AND LOWER(h.state) = LOWER(%s)
                  AND LOWER(p.specialty_name) LIKE LOWER(%s)
                LIMIT %s
                """,
                (city, state, f"%{specialty}%", limit),
            )
            return cur.fetchall()
    finally:
        conn.close()


def list_available_slots(doctor_id: str, limit: int = 5) -> list[dict]:
    """Read-only lookup (agent_reader) of a doctor's open slots."""
    conn = _reader_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT slot_id, date, time_slot, appointment_type, consultation_mode
                FROM doctoravailability
                WHERE doctor_id = %s AND is_available = 1
                ORDER BY date, time_slot
                LIMIT %s
                """,
                (doctor_id, limit),
            )
            return cur.fetchall()
    finally:
        conn.close()


def claim_slot_and_book(slot_id: str, patient_name: str, patient_email: str, patient_phone: str) -> dict:
    """
    Race-aware transactional write (agent_writer — the only place in the codebase that uses it).
    Returns {"outcome": "slot_taken"} or {"outcome": "success", "booking_id", "doctor_id",
    "appointment_date", "appointment_time"}.
    """
    conn = _writer_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE doctoravailability SET is_available = 0 WHERE slot_id = %s AND is_available = 1",
                (slot_id,),
            )
            if cur.rowcount == 0:
                conn.rollback()
                return {"outcome": "slot_taken"}

            cur.execute(
                "SELECT doctor_id, date, time_slot, appointment_type, consultation_mode "
                "FROM doctoravailability WHERE slot_id = %s",
                (slot_id,),
            )
            slot = cur.fetchone()

            booking_id = str(uuid.uuid4()).replace("-", "")[:20]
            cur.execute(
                "INSERT INTO appointments "
                "(booking_id, slot_id, doctor_id, patient_name, patient_phone, patient_email, "
                " appointment_date, appointment_time, appointment_type, consultation_mode, booking_status) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Confirmed')",
                (
                    booking_id, slot_id, slot["doctor_id"], patient_name, patient_phone, patient_email,
                    slot["date"], slot["time_slot"], slot["appointment_type"], slot["consultation_mode"],
                ),
            )
        conn.commit()
        return {
            "outcome": "success",
            "booking_id": booking_id,
            "doctor_id": slot["doctor_id"],
            "appointment_date": str(slot["date"]),
            "appointment_time": str(slot["time_slot"]),
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
