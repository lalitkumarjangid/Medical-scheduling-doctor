"""
Booking tool for creating, canceling, and rescheduling appointments.
"""

import os
from typing import Dict, Optional
import httpx
from models.schemas import AppointmentType, BookingRequest, PatientInfo


class BookingTool:
    """Tool for booking and managing appointments."""
    
    def __init__(self, api_base_url: str = "http://localhost:8000"):
        """
        Initialize the booking tool.
        
        Args:
            api_base_url: Base URL for the Calendly API endpoints
        """
        self.api_base_url = api_base_url
        # Check if we're using real Calendly API
        self.use_real_calendly = os.getenv("USE_REAL_CALENDLY", "false").lower() == "true"
        self.calendly_endpoint = "/api/calendly-live" if self.use_real_calendly else "/api/calendly"
    
    async def book_appointment(
        self,
        appointment_type: str,
        date: str,
        start_time: str,
        patient_name: str,
        patient_email: str,
        patient_phone: str,
        reason: str,
        scheduling_url: str = None
    ) -> Dict:
        """
        Book a new appointment.
        
        Args:
            appointment_type: Type of appointment (consultation, followup, physical, specialist)
            date: Date in YYYY-MM-DD format
            start_time: Start time in HH:MM format
            patient_name: Patient's full name
            patient_email: Patient's email address
            patient_phone: Patient's phone number
            reason: Reason for the visit
            scheduling_url: For real Calendly, the direct scheduling URL
            
        Returns:
            Dictionary with booking result
        """
        try:
            async with httpx.AsyncClient() as client:
                if self.use_real_calendly:
                    # For real Calendly, we provide the scheduling URL
                    # The user must click this link to complete the booking
                    # Calendly will then send confirmation emails automatically
                    
                    if scheduling_url:
                        return {
                            "success": True,
                            "booking_id": None,
                            "confirmation_code": None,
                            "status": "pending_user_action",
                            "details": {
                                "date": date,
                                "time": start_time,
                                "patient_name": patient_name,
                                "patient_email": patient_email,
                                "reason": reason
                            },
                            "scheduling_url": scheduling_url,
                            "message": "Please click the link below to complete your booking. Calendly will send you a confirmation email once booked."
                        }
                    else:
                        # Try to get a scheduling link
                        response = await client.get(
                            f"{self.api_base_url}/api/calendly-live/event-types"
                        )
                        if response.status_code == 200:
                            data = response.json()
                            event_types = data.get("event_types", [])
                            if event_types:
                                scheduling_url = event_types[0].get("scheduling_url")
                                return {
                                    "success": True,
                                    "booking_id": None,
                                    "confirmation_code": None,
                                    "status": "pending_user_action",
                                    "details": {
                                        "date": date,
                                        "time": start_time,
                                        "patient_name": patient_name,
                                        "patient_email": patient_email,
                                        "reason": reason
                                    },
                                    "scheduling_url": scheduling_url,
                                    "message": "Please click the link to complete your booking on Calendly."
                                }
                        
                        return {
                            "success": False,
                            "error": "Could not get Calendly scheduling link"
                        }
                else:
                    # Use mock Calendly API
                    booking_data = {
                        "appointment_type": appointment_type,
                        "date": date,
                        "start_time": start_time,
                        "patient": {
                            "name": patient_name,
                            "email": patient_email,
                            "phone": patient_phone
                        },
                        "reason": reason
                    }
                    
                    response = await client.post(
                        f"{self.api_base_url}/api/calendly/book",
                        json=booking_data
                    )
                
                    if response.status_code == 200:
                        data = response.json()
                        return {
                            "success": True,
                            "booking_id": data.get("booking_id"),
                            "confirmation_code": data.get("confirmation_code"),
                            "status": data.get("status"),
                            "details": data.get("details", {}),
                            "scheduling_url": None
                        }
                    else:
                        error_detail = response.json().get("detail", "Booking failed")
                        return {
                            "success": False,
                            "error": error_detail
                        }
        except Exception as e:
            return {
                "success": False,
                "error": f"Booking request failed: {str(e)}"
            }
    
    async def cancel_appointment(
        self,
        booking_id: str,
        confirmation_code: str,
        reason: Optional[str] = None
    ) -> Dict:
        """
        Cancel an existing appointment.
        
        Args:
            booking_id: The booking ID
            confirmation_code: The confirmation code
            reason: Optional reason for cancellation
            
        Returns:
            Dictionary with cancellation result
        """
        try:
            cancel_data = {
                "booking_id": booking_id,
                "confirmation_code": confirmation_code
            }
            if reason:
                cancel_data["reason"] = reason
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_base_url}/api/calendly/cancel",
                    json=cancel_data
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "success": True,
                        "message": data.get("message", "Appointment cancelled successfully")
                    }
                else:
                    error_detail = response.json().get("detail", "Cancellation failed")
                    return {
                        "success": False,
                        "error": error_detail
                    }
        except Exception as e:
            return {
                "success": False,
                "error": f"Cancellation request failed: {str(e)}"
            }
    
    async def reschedule_appointment(
        self,
        booking_id: str,
        confirmation_code: str,
        new_date: str,
        new_start_time: str
    ) -> Dict:
        """
        Reschedule an existing appointment.
        
        Args:
            booking_id: The booking ID
            confirmation_code: The confirmation code
            new_date: New date in YYYY-MM-DD format
            new_start_time: New start time in HH:MM format
            
        Returns:
            Dictionary with rescheduling result
        """
        try:
            reschedule_data = {
                "booking_id": booking_id,
                "confirmation_code": confirmation_code,
                "new_date": new_date,
                "new_start_time": new_start_time
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_base_url}/api/calendly/reschedule",
                    json=reschedule_data
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "success": True,
                        "message": data.get("message", "Appointment rescheduled successfully"),
                        "new_date": data.get("new_date"),
                        "new_start_time": data.get("new_start_time"),
                        "new_end_time": data.get("new_end_time")
                    }
                else:
                    error_detail = response.json().get("detail", "Rescheduling failed")
                    return {
                        "success": False,
                        "error": error_detail
                    }
        except Exception as e:
            return {
                "success": False,
                "error": f"Rescheduling request failed: {str(e)}"
            }
    
    async def get_appointment_details(self, booking_id: str) -> Dict:
        """
        Get details of an existing appointment.
        
        Args:
            booking_id: The booking ID
            
        Returns:
            Dictionary with appointment details
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.api_base_url}/api/calendly/appointments/{booking_id}"
                )
                
                if response.status_code == 200:
                    return {
                        "success": True,
                        "appointment": response.json()
                    }
                else:
                    return {
                        "success": False,
                        "error": "Appointment not found"
                    }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to retrieve appointment: {str(e)}"
            }
    
    def validate_patient_info(
        self,
        name: Optional[str],
        email: Optional[str],
        phone: Optional[str]
    ) -> Dict:
        """
        Validate patient information.
        
        Args:
            name: Patient's name
            email: Patient's email
            phone: Patient's phone
            
        Returns:
            Dictionary with validation result and missing fields
        """
        missing = []
        invalid = []
        
        if not name or len(name.strip()) < 2:
            missing.append("name")
        
        if not email:
            missing.append("email")
        elif "@" not in email or "." not in email:
            invalid.append("email")
        
        if not phone:
            missing.append("phone")
        else:
            # Basic phone validation - should have at least 10 digits
            digits = ''.join(c for c in phone if c.isdigit())
            if len(digits) < 10:
                invalid.append("phone")
        
        return {
            "valid": len(missing) == 0 and len(invalid) == 0,
            "missing_fields": missing,
            "invalid_fields": invalid
        }
    
    def format_confirmation_message(self, booking_result: Dict) -> str:
        """
        Format a booking confirmation message for the user.
        
        Args:
            booking_result: The result from book_appointment
            
        Returns:
            Formatted confirmation message
        """
        if not booking_result.get("success"):
            return f"I apologize, but I wasn't able to complete your booking. {booking_result.get('error', 'Please try again.')}"
        
        details = booking_result.get("details", {})
        confirmation_code = booking_result.get("confirmation_code", "N/A")
        
        # Format date nicely
        from datetime import datetime
        date_str = details.get("date", "")
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            formatted_date = date_obj.strftime("%A, %B %d, %Y")
        except ValueError:
            formatted_date = date_str
        
        # Format time nicely
        start_time = details.get("start_time", "")
        try:
            time_obj = datetime.strptime(start_time, "%H:%M")
            formatted_time = time_obj.strftime("%I:%M %p").lstrip("0")
        except ValueError:
            formatted_time = start_time
        
        message = f"""
🎉 **Your appointment is confirmed!**

📅 **Date:** {formatted_date}
🕐 **Time:** {formatted_time}
⏱️ **Duration:** {details.get('duration_minutes', 30)} minutes
📋 **Type:** {details.get('appointment_type', 'Consultation').replace('_', ' ').title()}

👤 **Patient:** {details.get('patient_name', '')}
📧 **Email:** {details.get('patient_email', '')}

🏥 **Location:** {details.get('clinic_name', 'HealthCare Plus Clinic')}
📍 **Address:** {details.get('clinic_address', '')}
📞 **Phone:** {details.get('clinic_phone', '')}

🔑 **Confirmation Code:** {confirmation_code}

Please save your confirmation code. You'll need it if you need to cancel or reschedule.

A confirmation email has been sent to {details.get('patient_email', 'your email address')}.

Is there anything else I can help you with?
""".strip()
        
        return message
