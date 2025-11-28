"""
Mock Calendly API Integration for the Medical Appointment Scheduling Agent.
Provides endpoints for checking availability and booking appointments.
"""

import json
import random
import string
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List
from fastapi import APIRouter, HTTPException

from models.schemas import (
    AppointmentType,
    APPOINTMENT_DURATIONS,
    AvailabilityRequest,
    AvailabilityResponse,
    TimeSlot,
    BookingRequest,
    BookingResponse,
    CancelRequest,
    RescheduleRequest,
)

router = APIRouter(prefix="/api/calendly", tags=["calendly"])

# Load schedule data
DATA_DIR = Path(__file__).parent.parent.parent / "data"


def load_schedule_data() -> dict:
    """Load doctor schedule from JSON file."""
    schedule_path = DATA_DIR / "doctor_schedule.json"
    with open(schedule_path, "r") as f:
        return json.load(f)


def save_schedule_data(data: dict) -> None:
    """Save updated schedule data to JSON file."""
    schedule_path = DATA_DIR / "doctor_schedule.json"
    with open(schedule_path, "w") as f:
        json.dump(data, f, indent=2)


def generate_confirmation_code() -> str:
    """Generate a random confirmation code."""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))


def generate_booking_id() -> str:
    """Generate a unique booking ID."""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_suffix = ''.join(random.choices(string.digits, k=3))
    return f"APPT-{timestamp}-{random_suffix}"


def get_day_name(date_str: str) -> str:
    """Get day name from date string."""
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    return date_obj.strftime("%A").lower()


def parse_time(time_str: str) -> datetime:
    """Parse time string to datetime object."""
    return datetime.strptime(time_str, "%H:%M")


def format_time(dt: datetime) -> str:
    """Format datetime to time string."""
    return dt.strftime("%H:%M")


def add_minutes(time_str: str, minutes: int) -> str:
    """Add minutes to a time string."""
    time_obj = parse_time(time_str)
    new_time = time_obj + timedelta(minutes=minutes)
    return format_time(new_time)


def time_overlaps(start1: str, end1: str, start2: str, end2: str) -> bool:
    """Check if two time ranges overlap."""
    s1, e1 = parse_time(start1), parse_time(end1)
    s2, e2 = parse_time(start2), parse_time(end2)
    return s1 < e2 and s2 < e1


def is_in_lunch_break(time_str: str, lunch_start: Optional[str], lunch_end: Optional[str]) -> bool:
    """Check if a time falls within lunch break."""
    if not lunch_start or not lunch_end:
        return False
    t = parse_time(time_str)
    ls = parse_time(lunch_start)
    le = parse_time(lunch_end)
    return ls <= t < le


def get_available_slots(
    date_str: str,
    appointment_type: AppointmentType,
    schedule_data: dict
) -> List[TimeSlot]:
    """
    Calculate available time slots for a given date and appointment type.
    """
    # Check if date is valid
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return []
    
    # Check if date is in the past
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if date_obj < today:
        return []
    
    # Get doctor info (using first doctor for now)
    doctor = schedule_data["doctors"][0]
    
    # Check if date is blocked
    if date_str in doctor.get("blocked_dates", []):
        return []
    
    # Get day name and working hours
    day_name = get_day_name(date_str)
    working_hours = doctor.get("working_hours", {}).get(day_name)
    
    if not working_hours:
        return []
    
    # Get appointment duration
    duration = APPOINTMENT_DURATIONS.get(appointment_type, 30)
    
    # Generate all possible slots
    start_time = working_hours["start"]
    end_time = working_hours["end"]
    lunch_start = working_hours.get("lunch_start")
    lunch_end = working_hours.get("lunch_end")
    
    slots = []
    current_time = start_time
    
    # Get existing appointments for this date
    existing_appointments = [
        appt for appt in schedule_data.get("existing_appointments", [])
        if appt["date"] == date_str
    ]
    
    while parse_time(current_time) < parse_time(end_time):
        slot_end = add_minutes(current_time, duration)
        
        # Check if slot extends beyond working hours
        if parse_time(slot_end) > parse_time(end_time):
            break
        
        # Check if slot is during lunch
        if is_in_lunch_break(current_time, lunch_start, lunch_end):
            current_time = lunch_end
            continue
        
        # Check if slot end is during lunch
        if lunch_start and lunch_end:
            if parse_time(current_time) < parse_time(lunch_start) and parse_time(slot_end) > parse_time(lunch_start):
                current_time = lunch_end
                continue
        
        # Check if slot conflicts with existing appointments
        is_available = True
        for appt in existing_appointments:
            if time_overlaps(current_time, slot_end, appt["start_time"], appt["end_time"]):
                is_available = False
                break
        
        # For today, check if slot is in the past
        if date_obj.date() == datetime.now().date():
            now = datetime.now()
            slot_start_dt = datetime.strptime(f"{date_str} {current_time}", "%Y-%m-%d %H:%M")
            if slot_start_dt <= now:
                is_available = False
        
        slots.append(TimeSlot(
            start_time=current_time,
            end_time=slot_end,
            available=is_available
        ))
        
        # Move to next slot
        current_time = add_minutes(current_time, schedule_data["settings"]["slot_interval_minutes"])
    
    return slots


@router.get("/availability", response_model=AvailabilityResponse)
async def get_availability(date: str, appointment_type: str = "consultation"):
    """
    Get available time slots for a specific date and appointment type.
    
    - **date**: Date in YYYY-MM-DD format
    - **appointment_type**: Type of appointment (consultation, followup, physical, specialist)
    """
    try:
        # Validate date format
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    
    # Map appointment type string to enum
    try:
        appt_type = AppointmentType(appointment_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid appointment type. Valid types: {[t.value for t in AppointmentType]}"
        )
    
    # Load schedule and get available slots
    schedule_data = load_schedule_data()
    slots = get_available_slots(date, appt_type, schedule_data)
    
    return AvailabilityResponse(
        date=date,
        appointment_type=appointment_type,
        duration_minutes=APPOINTMENT_DURATIONS[appt_type],
        available_slots=slots
    )


@router.post("/book", response_model=BookingResponse)
async def book_appointment(booking: BookingRequest):
    """
    Book an appointment.
    
    Creates a new appointment in the schedule.
    """
    # Load current schedule
    schedule_data = load_schedule_data()
    
    # Validate the slot is still available
    slots = get_available_slots(booking.date, booking.appointment_type, schedule_data)
    
    slot_available = False
    for slot in slots:
        if slot.start_time == booking.start_time and slot.available:
            slot_available = True
            break
    
    if not slot_available:
        raise HTTPException(
            status_code=409,
            detail="The selected time slot is no longer available. Please choose another slot."
        )
    
    # Calculate end time
    duration = APPOINTMENT_DURATIONS[booking.appointment_type]
    end_time = add_minutes(booking.start_time, duration)
    
    # Generate booking ID and confirmation code
    booking_id = generate_booking_id()
    confirmation_code = generate_confirmation_code()
    
    # Create appointment record
    new_appointment = {
        "id": booking_id,
        "doctor_id": "dr-001",
        "date": booking.date,
        "start_time": booking.start_time,
        "end_time": end_time,
        "type": booking.appointment_type.value,
        "patient_name": booking.patient.name,
        "patient_email": booking.patient.email,
        "patient_phone": booking.patient.phone,
        "reason": booking.reason,
        "confirmation_code": confirmation_code,
        "status": "confirmed",
        "created_at": datetime.now().isoformat()
    }
    
    # Add to existing appointments
    schedule_data["existing_appointments"].append(new_appointment)
    
    # Save updated schedule
    save_schedule_data(schedule_data)
    
    return BookingResponse(
        booking_id=booking_id,
        status="confirmed",
        confirmation_code=confirmation_code,
        details={
            "date": booking.date,
            "start_time": booking.start_time,
            "end_time": end_time,
            "duration_minutes": duration,
            "appointment_type": booking.appointment_type.value,
            "patient_name": booking.patient.name,
            "patient_email": booking.patient.email,
            "doctor_name": "Dr. Sarah Johnson",
            "clinic_name": "HealthCare Plus Clinic",
            "clinic_phone": "+1-555-123-4567",
            "clinic_address": "123 Medical Center Drive, Suite 200, Springfield, IL 62701"
        }
    )


@router.post("/cancel")
async def cancel_appointment(cancel_request: CancelRequest):
    """
    Cancel an existing appointment.
    """
    schedule_data = load_schedule_data()
    
    # Find the appointment
    appointment_idx = None
    for idx, appt in enumerate(schedule_data["existing_appointments"]):
        if appt["id"] == cancel_request.booking_id:
            if appt.get("confirmation_code") == cancel_request.confirmation_code:
                appointment_idx = idx
                break
            else:
                raise HTTPException(status_code=403, detail="Invalid confirmation code.")
    
    if appointment_idx is None:
        raise HTTPException(status_code=404, detail="Appointment not found.")
    
    # Remove the appointment
    cancelled_appt = schedule_data["existing_appointments"].pop(appointment_idx)
    
    # Save updated schedule
    save_schedule_data(schedule_data)
    
    return {
        "status": "cancelled",
        "booking_id": cancel_request.booking_id,
        "message": f"Your appointment on {cancelled_appt['date']} at {cancelled_appt['start_time']} has been cancelled."
    }


@router.post("/reschedule")
async def reschedule_appointment(reschedule_request: RescheduleRequest):
    """
    Reschedule an existing appointment.
    """
    schedule_data = load_schedule_data()
    
    # Find the appointment
    appointment_idx = None
    original_appt = None
    for idx, appt in enumerate(schedule_data["existing_appointments"]):
        if appt["id"] == reschedule_request.booking_id:
            if appt.get("confirmation_code") == reschedule_request.confirmation_code:
                appointment_idx = idx
                original_appt = appt
                break
            else:
                raise HTTPException(status_code=403, detail="Invalid confirmation code.")
    
    if appointment_idx is None:
        raise HTTPException(status_code=404, detail="Appointment not found.")
    
    # Check if new slot is available
    appt_type = AppointmentType(original_appt["type"])
    
    # Temporarily remove the appointment to check availability
    schedule_data["existing_appointments"].pop(appointment_idx)
    slots = get_available_slots(reschedule_request.new_date, appt_type, schedule_data)
    
    slot_available = False
    for slot in slots:
        if slot.start_time == reschedule_request.new_start_time and slot.available:
            slot_available = True
            break
    
    if not slot_available:
        # Restore the original appointment
        schedule_data["existing_appointments"].insert(appointment_idx, original_appt)
        raise HTTPException(
            status_code=409,
            detail="The selected time slot is not available. Please choose another slot."
        )
    
    # Calculate new end time
    duration = APPOINTMENT_DURATIONS[appt_type]
    new_end_time = add_minutes(reschedule_request.new_start_time, duration)
    
    # Update appointment
    original_appt["date"] = reschedule_request.new_date
    original_appt["start_time"] = reschedule_request.new_start_time
    original_appt["end_time"] = new_end_time
    original_appt["updated_at"] = datetime.now().isoformat()
    
    schedule_data["existing_appointments"].append(original_appt)
    
    # Save updated schedule
    save_schedule_data(schedule_data)
    
    return {
        "status": "rescheduled",
        "booking_id": reschedule_request.booking_id,
        "new_date": reschedule_request.new_date,
        "new_start_time": reschedule_request.new_start_time,
        "new_end_time": new_end_time,
        "message": f"Your appointment has been rescheduled to {reschedule_request.new_date} at {reschedule_request.new_start_time}."
    }


@router.get("/appointments/{booking_id}")
async def get_appointment(booking_id: str):
    """
    Get details of a specific appointment.
    """
    schedule_data = load_schedule_data()
    
    for appt in schedule_data["existing_appointments"]:
        if appt["id"] == booking_id:
            return appt
    
    raise HTTPException(status_code=404, detail="Appointment not found.")


@router.get("/appointments")
async def get_all_appointments(
    status: Optional[str] = None,
    date: Optional[str] = None,
    patient_email: Optional[str] = None
):
    """
    Get all booked appointments with optional filters.
    
    - **status**: Filter by status (confirmed, cancelled, completed)
    - **date**: Filter by specific date (YYYY-MM-DD)
    - **patient_email**: Filter by patient email
    """
    schedule_data = load_schedule_data()
    appointments = schedule_data.get("existing_appointments", [])
    
    # Apply filters
    if status:
        appointments = [a for a in appointments if a.get("status") == status]
    
    if date:
        appointments = [a for a in appointments if a.get("date") == date]
    
    if patient_email:
        appointments = [a for a in appointments if a.get("patient_email") == patient_email]
    
    # Sort by date and time
    appointments = sorted(
        appointments,
        key=lambda x: (x.get("date", ""), x.get("start_time", ""))
    )
    
    # Format appointments for display
    formatted_appointments = []
    for appt in appointments:
        formatted_appointments.append({
            "booking_id": appt.get("id"),
            "confirmation_code": appt.get("confirmation_code"),
            "date": appt.get("date"),
            "day_name": get_day_name(appt.get("date", datetime.now().strftime("%Y-%m-%d"))).capitalize(),
            "start_time": appt.get("start_time"),
            "end_time": appt.get("end_time"),
            "appointment_type": appt.get("type"),
            "patient_name": appt.get("patient_name"),
            "patient_email": appt.get("patient_email"),
            "patient_phone": appt.get("patient_phone"),
            "reason": appt.get("reason"),
            "status": appt.get("status"),
            "doctor_name": "Dr. Sarah Johnson",
            "created_at": appt.get("created_at")
        })
    
    return {
        "total": len(formatted_appointments),
        "appointments": formatted_appointments
    }


@router.get("/my-appointments")
async def get_my_appointments(email: str):
    """
    Get all appointments for a specific patient by email.
    
    - **email**: Patient's email address
    """
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
    
    schedule_data = load_schedule_data()
    appointments = schedule_data.get("existing_appointments", [])
    
    # Filter by patient email
    patient_appointments = [a for a in appointments if a.get("patient_email", "").lower() == email.lower()]
    
    # Categorize appointments
    today = datetime.now().strftime("%Y-%m-%d")
    
    upcoming = []
    past = []
    
    for appt in patient_appointments:
        appt_info = {
            "booking_id": appt.get("id"),
            "confirmation_code": appt.get("confirmation_code"),
            "date": appt.get("date"),
            "day_name": get_day_name(appt.get("date", today)).capitalize(),
            "start_time": appt.get("start_time"),
            "end_time": appt.get("end_time"),
            "appointment_type": appt.get("type"),
            "reason": appt.get("reason"),
            "status": appt.get("status"),
            "doctor_name": "Dr. Sarah Johnson"
        }
        
        if appt.get("date", "") >= today and appt.get("status") == "confirmed":
            upcoming.append(appt_info)
        else:
            past.append(appt_info)
    
    # Sort upcoming by date/time ascending, past by date/time descending
    upcoming = sorted(upcoming, key=lambda x: (x["date"], x["start_time"]))
    past = sorted(past, key=lambda x: (x["date"], x["start_time"]), reverse=True)
    
    return {
        "email": email,
        "upcoming_appointments": upcoming,
        "past_appointments": past,
        "total_upcoming": len(upcoming),
        "total_past": len(past)
    }


@router.get("/schedule/dates")
async def get_available_dates(days_ahead: int = 14, appointment_type: str = "consultation"):
    """
    Get list of dates with available slots in the next N days.
    Useful for showing a calendar with available dates.
    """
    try:
        appt_type = AppointmentType(appointment_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid appointment type. Valid types: {[t.value for t in AppointmentType]}"
        )
    
    schedule_data = load_schedule_data()
    available_dates = []
    
    today = datetime.now()
    
    for i in range(days_ahead):
        check_date = today + timedelta(days=i)
        date_str = check_date.strftime("%Y-%m-%d")
        
        slots = get_available_slots(date_str, appt_type, schedule_data)
        available_count = sum(1 for slot in slots if slot.available)
        
        if available_count > 0:
            available_dates.append({
                "date": date_str,
                "day_name": check_date.strftime("%A"),
                "available_slots": available_count
            })
    
    return {"available_dates": available_dates}
