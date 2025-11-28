"""
Availability tool for checking doctor's available time slots.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Optional
import httpx
from models.schemas import AppointmentType, APPOINTMENT_DURATIONS


class AvailabilityTool:
    """Tool for checking appointment availability."""
    
    def __init__(self, api_base_url: str = "http://localhost:8000"):
        """
        Initialize the availability tool.
        
        Args:
            api_base_url: Base URL for the Calendly API endpoints
        """
        self.api_base_url = api_base_url
    
    async def get_available_slots(
        self,
        date: str,
        appointment_type: str = "consultation"
    ) -> Dict:
        """
        Get available time slots for a specific date.
        
        Args:
            date: Date in YYYY-MM-DD format
            appointment_type: Type of appointment
            
        Returns:
            Dictionary with available slots and metadata
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.api_base_url}/api/calendly/availability",
                params={"date": date, "appointment_type": appointment_type}
            )
            
            if response.status_code == 200:
                data = response.json()
                # Filter to only available slots
                available_only = [
                    slot for slot in data.get("available_slots", [])
                    if slot.get("available", False)
                ]
                return {
                    "success": True,
                    "date": data.get("date"),
                    "appointment_type": data.get("appointment_type"),
                    "duration_minutes": data.get("duration_minutes"),
                    "available_slots": available_only,
                    "total_available": len(available_only)
                }
            else:
                return {
                    "success": False,
                    "error": response.json().get("detail", "Failed to fetch availability")
                }
    
    async def get_available_dates(
        self,
        days_ahead: int = 14,
        appointment_type: str = "consultation"
    ) -> Dict:
        """
        Get dates with available slots in the upcoming days.
        
        Args:
            days_ahead: Number of days to look ahead
            appointment_type: Type of appointment
            
        Returns:
            Dictionary with available dates
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.api_base_url}/api/calendly/schedule/dates",
                params={"days_ahead": days_ahead, "appointment_type": appointment_type}
            )
            
            if response.status_code == 200:
                return {
                    "success": True,
                    **response.json()
                }
            else:
                return {
                    "success": False,
                    "error": response.json().get("detail", "Failed to fetch available dates")
                }
    
    def get_slots_for_time_preference(
        self,
        available_slots: List[Dict],
        preference: str
    ) -> List[Dict]:
        """
        Filter slots based on time of day preference.
        
        Args:
            available_slots: List of available time slots
            preference: "morning", "afternoon", "evening", or "any"
            
        Returns:
            Filtered list of slots matching the preference
        """
        if preference == "any" or not preference:
            return available_slots
        
        filtered = []
        for slot in available_slots:
            start_time = slot.get("start_time", "")
            hour = int(start_time.split(":")[0]) if start_time else 0
            
            if preference == "morning" and 6 <= hour < 12:
                filtered.append(slot)
            elif preference == "afternoon" and 12 <= hour < 17:
                filtered.append(slot)
            elif preference == "evening" and 17 <= hour < 21:
                filtered.append(slot)
        
        return filtered
    
    def format_slot_for_display(self, slot: Dict, date: str) -> str:
        """
        Format a time slot for user-friendly display.
        
        Args:
            slot: Time slot dictionary
            date: Date string
            
        Returns:
            Formatted string for display
        """
        start = slot.get("start_time", "")
        
        # Convert to 12-hour format
        try:
            time_obj = datetime.strptime(start, "%H:%M")
            formatted_time = time_obj.strftime("%I:%M %p").lstrip("0")
        except ValueError:
            formatted_time = start
        
        # Format date
        try:
            date_obj = datetime.strptime(date, "%Y-%m-%d")
            formatted_date = date_obj.strftime("%A, %B %d")
        except ValueError:
            formatted_date = date
        
        return f"{formatted_date} at {formatted_time}"
    
    def suggest_alternative_dates(
        self,
        preferred_date: str,
        available_dates: List[Dict],
        count: int = 3
    ) -> List[Dict]:
        """
        Suggest alternative dates when preferred date has no availability.
        
        Args:
            preferred_date: The originally requested date
            available_dates: List of dates with availability
            count: Number of alternatives to suggest
            
        Returns:
            List of suggested alternative dates
        """
        try:
            pref_date = datetime.strptime(preferred_date, "%Y-%m-%d")
        except ValueError:
            return available_dates[:count]
        
        # Sort by closeness to preferred date
        def date_distance(date_info):
            try:
                d = datetime.strptime(date_info["date"], "%Y-%m-%d")
                return abs((d - pref_date).days)
            except ValueError:
                return float('inf')
        
        sorted_dates = sorted(available_dates, key=date_distance)
        return sorted_dates[:count]


def parse_date_reference(text: str, reference_date: Optional[datetime] = None) -> Optional[str]:
    """
    Parse natural language date references to YYYY-MM-DD format.
    
    Args:
        text: Natural language date (e.g., "tomorrow", "next Monday")
        reference_date: Reference date (defaults to today)
        
    Returns:
        Date string in YYYY-MM-DD format or None if unable to parse
    """
    if reference_date is None:
        reference_date = datetime.now()
    
    text_lower = text.lower().strip()
    
    # Direct date patterns
    if "today" in text_lower:
        return reference_date.strftime("%Y-%m-%d")
    
    if "tomorrow" in text_lower:
        return (reference_date + timedelta(days=1)).strftime("%Y-%m-%d")
    
    # Day of week patterns
    days = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6
    }
    
    for day_name, day_num in days.items():
        if day_name in text_lower:
            current_day = reference_date.weekday()
            days_until = (day_num - current_day) % 7
            
            # If "next" is mentioned, add a week
            if "next" in text_lower and days_until == 0:
                days_until = 7
            elif days_until == 0 and "this" not in text_lower:
                # If the day is today and not explicitly "this", assume next week
                days_until = 7
            
            target_date = reference_date + timedelta(days=days_until)
            return target_date.strftime("%Y-%m-%d")
    
    # "Next week" pattern
    if "next week" in text_lower:
        # Return Monday of next week
        current_day = reference_date.weekday()
        days_until_monday = (7 - current_day) % 7 + (7 if current_day == 0 else 0)
        target_date = reference_date + timedelta(days=days_until_monday)
        return target_date.strftime("%Y-%m-%d")
    
    # "This week" pattern - return tomorrow if still this week
    if "this week" in text_lower:
        return (reference_date + timedelta(days=1)).strftime("%Y-%m-%d")
    
    # Try to parse as a date
    date_formats = ["%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%d/%m/%Y", "%B %d", "%b %d"]
    for fmt in date_formats:
        try:
            parsed = datetime.strptime(text, fmt)
            # If year not in format, use current year
            if "%Y" not in fmt and "%y" not in fmt:
                parsed = parsed.replace(year=reference_date.year)
                # If the date is in the past, use next year
                if parsed < reference_date:
                    parsed = parsed.replace(year=reference_date.year + 1)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue
    
    return None


def parse_time_preference(text: str) -> str:
    """
    Parse time of day preference from text.
    
    Args:
        text: Natural language time preference
        
    Returns:
        "morning", "afternoon", "evening", or "any"
    """
    text_lower = text.lower()
    
    if any(word in text_lower for word in ["morning", "am", "early"]):
        return "morning"
    elif any(word in text_lower for word in ["afternoon", "lunch", "midday"]):
        return "afternoon"
    elif any(word in text_lower for word in ["evening", "pm", "late", "after work", "after 5"]):
        return "evening"
    
    return "any"
