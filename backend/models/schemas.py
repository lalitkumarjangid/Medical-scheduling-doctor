"""
Pydantic models and schemas for the Medical Appointment Scheduling Agent.
"""

from datetime import datetime, date, time
from typing import Optional, List, Literal
from pydantic import BaseModel, EmailStr, Field
from enum import Enum


class AppointmentType(str, Enum):
    """Types of appointments with their durations."""
    GENERAL_CONSULTATION = "consultation"
    FOLLOW_UP = "followup"
    PHYSICAL_EXAM = "physical"
    SPECIALIST_CONSULTATION = "specialist"


APPOINTMENT_DURATIONS = {
    AppointmentType.GENERAL_CONSULTATION: 30,
    AppointmentType.FOLLOW_UP: 15,
    AppointmentType.PHYSICAL_EXAM: 45,
    AppointmentType.SPECIALIST_CONSULTATION: 60,
}


class TimeSlot(BaseModel):
    """Represents a single time slot."""
    start_time: str
    end_time: str
    available: bool = True


class AvailabilityRequest(BaseModel):
    """Request for checking availability."""
    date: str = Field(..., description="Date in YYYY-MM-DD format")
    appointment_type: AppointmentType = AppointmentType.GENERAL_CONSULTATION


class AvailabilityResponse(BaseModel):
    """Response with available time slots."""
    date: str
    appointment_type: str
    duration_minutes: int
    available_slots: List[TimeSlot]


class PatientInfo(BaseModel):
    """Patient information for booking."""
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    phone: str = Field(..., pattern=r"^\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}$")


class BookingRequest(BaseModel):
    """Request to book an appointment."""
    appointment_type: AppointmentType
    date: str = Field(..., description="Date in YYYY-MM-DD format")
    start_time: str = Field(..., description="Time in HH:MM format")
    patient: PatientInfo
    reason: str = Field(..., min_length=3, max_length=500)


class BookingResponse(BaseModel):
    """Response after successful booking."""
    booking_id: str
    status: Literal["confirmed", "pending", "failed"]
    confirmation_code: str
    details: dict


class CancelRequest(BaseModel):
    """Request to cancel an appointment."""
    booking_id: str
    confirmation_code: str
    reason: Optional[str] = None


class RescheduleRequest(BaseModel):
    """Request to reschedule an appointment."""
    booking_id: str
    confirmation_code: str
    new_date: str
    new_start_time: str


# Chat Models
class ChatMessage(BaseModel):
    """A single chat message."""
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: Optional[datetime] = None


class ChatRequest(BaseModel):
    """Request to the chat endpoint."""
    message: str
    session_id: Optional[str] = None
    context: Optional[dict] = None


class ChatResponse(BaseModel):
    """Response from the chat endpoint."""
    message: str
    session_id: str
    intent: Optional[str] = None
    booking_status: Optional[dict] = None
    suggested_slots: Optional[List[dict]] = None


# Conversation State
class ConversationPhase(str, Enum):
    """Phases of the scheduling conversation."""
    GREETING = "greeting"
    UNDERSTANDING_NEEDS = "understanding_needs"
    COLLECTING_PREFERENCES = "collecting_preferences"
    SLOT_RECOMMENDATION = "slot_recommendation"
    COLLECTING_INFO = "collecting_info"
    CONFIRMATION = "confirmation"
    COMPLETED = "completed"
    FAQ = "faq"


class ConversationState(BaseModel):
    """Tracks the state of a scheduling conversation."""
    session_id: str
    phase: ConversationPhase = ConversationPhase.GREETING
    appointment_type: Optional[AppointmentType] = None
    preferred_date: Optional[str] = None
    preferred_time_of_day: Optional[str] = None  # morning, afternoon, evening
    selected_slot: Optional[dict] = None
    patient_info: Optional[dict] = None
    reason_for_visit: Optional[str] = None
    messages: List[ChatMessage] = []
    pending_faq: bool = False  # True if we need to return to scheduling after FAQ
    available_slots: Optional[List[dict]] = None  # Store available slots for reference
    scheduling_url: Optional[str] = None  # For real Calendly bookings
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    
    class Config:
        # Allow setting extra attributes dynamically
        extra = "allow"


# RAG Models
class FAQQuery(BaseModel):
    """Query for FAQ retrieval."""
    question: str
    top_k: int = 3


class FAQResult(BaseModel):
    """Result from FAQ retrieval."""
    question: str
    answer: str
    category: str
    confidence: float


# Doctor Schedule
class WorkingHours(BaseModel):
    """Doctor's working hours for a day."""
    day: str
    start_time: str
    end_time: str
    is_working: bool = True
    lunch_start: Optional[str] = "12:00"
    lunch_end: Optional[str] = "13:00"


class DoctorSchedule(BaseModel):
    """Complete doctor schedule."""
    doctor_name: str
    specialty: str
    working_hours: List[WorkingHours]
    blocked_dates: List[str] = []  # Vacation, holidays, etc.
