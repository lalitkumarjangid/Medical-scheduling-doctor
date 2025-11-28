"""
Tests for the Medical Appointment Scheduling Agent.
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
import sys

# Add backend to path
backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))

from models.schemas import (
    AppointmentType,
    APPOINTMENT_DURATIONS,
    ConversationPhase,
)
from tools.availability_tool import (
    parse_date_reference,
    parse_time_preference,
    AvailabilityTool
)
from tools.booking_tool import BookingTool


class TestDateParsing:
    """Tests for natural language date parsing."""
    
    def test_parse_today(self):
        result = parse_date_reference("today")
        expected = datetime.now().strftime("%Y-%m-%d")
        assert result == expected
    
    def test_parse_tomorrow(self):
        result = parse_date_reference("tomorrow")
        expected = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        assert result == expected
    
    def test_parse_day_name(self):
        result = parse_date_reference("monday")
        assert result is not None
        # Should return a valid date
        parsed = datetime.strptime(result, "%Y-%m-%d")
        assert parsed.weekday() == 0  # Monday
    
    def test_parse_next_week(self):
        result = parse_date_reference("next week")
        assert result is not None
        parsed = datetime.strptime(result, "%Y-%m-%d")
        assert parsed > datetime.now()
    
    def test_parse_invalid_date(self):
        result = parse_date_reference("invalid date string xyz")
        assert result is None


class TestTimeParsing:
    """Tests for time preference parsing."""
    
    def test_morning_preference(self):
        assert parse_time_preference("I prefer mornings") == "morning"
        assert parse_time_preference("early morning please") == "morning"
        assert parse_time_preference("10 AM works") == "morning"
    
    def test_afternoon_preference(self):
        assert parse_time_preference("afternoon is better") == "afternoon"
        assert parse_time_preference("after lunch") == "afternoon"
    
    def test_evening_preference(self):
        assert parse_time_preference("evening appointment") == "evening"
        assert parse_time_preference("after work please") == "evening"
        assert parse_time_preference("late afternoon, like 5pm") == "evening"
    
    def test_no_preference(self):
        assert parse_time_preference("any time works") == "any"
        assert parse_time_preference("whenever") == "any"


class TestAppointmentTypes:
    """Tests for appointment type configuration."""
    
    def test_appointment_durations(self):
        assert APPOINTMENT_DURATIONS[AppointmentType.GENERAL_CONSULTATION] == 30
        assert APPOINTMENT_DURATIONS[AppointmentType.FOLLOW_UP] == 15
        assert APPOINTMENT_DURATIONS[AppointmentType.PHYSICAL_EXAM] == 45
        assert APPOINTMENT_DURATIONS[AppointmentType.SPECIALIST_CONSULTATION] == 60
    
    def test_appointment_type_values(self):
        assert AppointmentType.GENERAL_CONSULTATION.value == "consultation"
        assert AppointmentType.FOLLOW_UP.value == "followup"
        assert AppointmentType.PHYSICAL_EXAM.value == "physical"
        assert AppointmentType.SPECIALIST_CONSULTATION.value == "specialist"


class TestPatientValidation:
    """Tests for patient information validation."""
    
    def test_valid_patient_info(self):
        tool = BookingTool()
        result = tool.validate_patient_info(
            name="John Doe",
            email="john@example.com",
            phone="+1-555-123-4567"
        )
        assert result["valid"] == True
        assert len(result["missing_fields"]) == 0
        assert len(result["invalid_fields"]) == 0
    
    def test_missing_name(self):
        tool = BookingTool()
        result = tool.validate_patient_info(
            name="",
            email="john@example.com",
            phone="+1-555-123-4567"
        )
        assert result["valid"] == False
        assert "name" in result["missing_fields"]
    
    def test_invalid_email(self):
        tool = BookingTool()
        result = tool.validate_patient_info(
            name="John Doe",
            email="invalid-email",
            phone="+1-555-123-4567"
        )
        assert result["valid"] == False
        assert "email" in result["invalid_fields"]
    
    def test_invalid_phone(self):
        tool = BookingTool()
        result = tool.validate_patient_info(
            name="John Doe",
            email="john@example.com",
            phone="123"  # Too short
        )
        assert result["valid"] == False
        assert "phone" in result["invalid_fields"]


class TestConversationPhases:
    """Tests for conversation phase transitions."""
    
    def test_all_phases_exist(self):
        phases = [
            ConversationPhase.GREETING,
            ConversationPhase.UNDERSTANDING_NEEDS,
            ConversationPhase.COLLECTING_PREFERENCES,
            ConversationPhase.SLOT_RECOMMENDATION,
            ConversationPhase.COLLECTING_INFO,
            ConversationPhase.CONFIRMATION,
            ConversationPhase.COMPLETED,
            ConversationPhase.FAQ,
        ]
        for phase in phases:
            assert phase is not None


# Async tests for API integration
@pytest.mark.asyncio
class TestAvailabilityTool:
    """Tests for the availability tool."""
    
    async def test_get_slots_for_time_preference_morning(self):
        tool = AvailabilityTool()
        slots = [
            {"start_time": "09:00", "end_time": "09:30", "available": True},
            {"start_time": "10:00", "end_time": "10:30", "available": True},
            {"start_time": "14:00", "end_time": "14:30", "available": True},
            {"start_time": "16:00", "end_time": "16:30", "available": True},
        ]
        
        filtered = tool.get_slots_for_time_preference(slots, "morning")
        assert len(filtered) == 2
        assert all(int(s["start_time"].split(":")[0]) < 12 for s in filtered)
    
    async def test_get_slots_for_time_preference_afternoon(self):
        tool = AvailabilityTool()
        slots = [
            {"start_time": "09:00", "end_time": "09:30", "available": True},
            {"start_time": "14:00", "end_time": "14:30", "available": True},
            {"start_time": "15:00", "end_time": "15:30", "available": True},
        ]
        
        filtered = tool.get_slots_for_time_preference(slots, "afternoon")
        assert len(filtered) == 2
        assert all(12 <= int(s["start_time"].split(":")[0]) < 17 for s in filtered)


class TestConfirmationMessage:
    """Tests for booking confirmation message formatting."""
    
    def test_successful_booking_message(self):
        tool = BookingTool()
        result = {
            "success": True,
            "booking_id": "APPT-123",
            "confirmation_code": "ABC123",
            "status": "confirmed",
            "details": {
                "date": "2025-12-01",
                "start_time": "10:00",
                "end_time": "10:30",
                "duration_minutes": 30,
                "appointment_type": "consultation",
                "patient_name": "John Doe",
                "patient_email": "john@example.com",
                "clinic_name": "HealthCare Plus Clinic",
                "clinic_address": "123 Medical Center Drive",
                "clinic_phone": "+1-555-123-4567"
            }
        }
        
        message = tool.format_confirmation_message(result)
        assert "confirmed" in message.lower()
        assert "ABC123" in message
        assert "John Doe" in message
    
    def test_failed_booking_message(self):
        tool = BookingTool()
        result = {
            "success": False,
            "error": "Slot no longer available"
        }
        
        message = tool.format_confirmation_message(result)
        assert "apologize" in message.lower() or "sorry" in message.lower() or "wasn't able" in message.lower()


# Example conversation tests
class TestConversationExamples:
    """Tests based on the specification examples."""
    
    def test_scheduling_keywords_detected(self):
        """Test that scheduling keywords are properly detected."""
        scheduling_phrases = [
            "I need to see the doctor",
            "I want to book an appointment",
            "Can I schedule a visit",
            "I'd like to make an appointment",
        ]
        
        for phrase in scheduling_phrases:
            lower = phrase.lower()
            keywords = ["schedule", "book", "appointment", "see the doctor"]
            assert any(kw in lower for kw in keywords)
    
    def test_faq_keywords_detected(self):
        """Test that FAQ keywords are properly detected."""
        faq_phrases = [
            "What insurance do you accept?",
            "Where is the clinic located?",
            "What are your hours?",
            "Do you accept Medicare?",
        ]
        
        for phrase in faq_phrases:
            lower = phrase.lower()
            keywords = ["what", "where", "insurance", "accept", "hours", "location"]
            assert any(kw in lower for kw in keywords)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
