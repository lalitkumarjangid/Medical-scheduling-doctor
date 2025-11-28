"""
Real Calendly API Integration for the Medical Appointment Scheduling Agent.
Connects to the actual Calendly API for production use.

Calendly API Documentation: https://developer.calendly.com/api-docs
"""

import os
import httpx
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from models.schemas import (
    AppointmentType,
    APPOINTMENT_DURATIONS,
    TimeSlot,
)

router = APIRouter(prefix="/api/calendly-live", tags=["calendly-live"])

# Calendly API configuration
CALENDLY_API_BASE = "https://api.calendly.com"
CALENDLY_API_KEY = os.getenv("CALENDLY_API_KEY", "")
CALENDLY_USER_URL = os.getenv("CALENDLY_USER_URL", "")


def get_headers() -> Dict[str, str]:
    """Get authorization headers for Calendly API."""
    if not CALENDLY_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="Calendly API key not configured. Set CALENDLY_API_KEY environment variable."
        )
    return {
        "Authorization": f"Bearer {CALENDLY_API_KEY}",
        "Content-Type": "application/json"
    }


class CalendlyClient:
    """Client for interacting with Calendly API."""
    
    def __init__(self):
        self.base_url = CALENDLY_API_BASE
        self.api_key = CALENDLY_API_KEY
        
    async def _request(self, method: str, endpoint: str, **kwargs) -> Dict:
        """Make an authenticated request to Calendly API."""
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method,
                f"{self.base_url}{endpoint}",
                headers=get_headers(),
                **kwargs
            )
            
            if response.status_code == 401:
                raise HTTPException(status_code=401, detail="Invalid Calendly API key")
            elif response.status_code == 403:
                raise HTTPException(status_code=403, detail="Forbidden - check API permissions")
            elif response.status_code == 404:
                raise HTTPException(status_code=404, detail="Resource not found")
            elif response.status_code >= 400:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Calendly API error: {response.text}"
                )
            
            return response.json()
    
    async def get_current_user(self) -> Dict:
        """Get the current authenticated user."""
        result = await self._request("GET", "/users/me")
        return result.get("resource", {})
    
    async def get_event_types(self, user_uri: Optional[str] = None) -> List[Dict]:
        """
        Get all event types for the user.
        
        Args:
            user_uri: User URI (defaults to current user)
            
        Returns:
            List of event types
        """
        if not user_uri:
            user = await self.get_current_user()
            user_uri = user.get("uri")
        
        params = {"user": user_uri}
        result = await self._request("GET", "/event_types", params=params)
        return result.get("collection", [])
    
    async def get_available_times(
        self,
        event_type_uri: str,
        start_time: str,
        end_time: str
    ) -> List[Dict]:
        """
        Get available times for an event type.
        
        Args:
            event_type_uri: The URI of the event type
            start_time: Start of time range (ISO 8601)
            end_time: End of time range (ISO 8601)
            
        Returns:
            List of available time slots
        """
        params = {
            "event_type": event_type_uri,
            "start_time": start_time,
            "end_time": end_time
        }
        result = await self._request("GET", "/event_type_available_times", params=params)
        return result.get("collection", [])
    
    async def get_scheduled_events(
        self,
        user_uri: Optional[str] = None,
        min_start_time: Optional[str] = None,
        max_start_time: Optional[str] = None,
        status: str = "active"
    ) -> List[Dict]:
        """
        Get scheduled events.
        
        Args:
            user_uri: User URI
            min_start_time: Minimum start time (ISO 8601)
            max_start_time: Maximum start time (ISO 8601)
            status: Event status (active, canceled)
            
        Returns:
            List of scheduled events
        """
        if not user_uri:
            user = await self.get_current_user()
            user_uri = user.get("uri")
        
        params = {"user": user_uri, "status": status}
        if min_start_time:
            params["min_start_time"] = min_start_time
        if max_start_time:
            params["max_start_time"] = max_start_time
            
        result = await self._request("GET", "/scheduled_events", params=params)
        return result.get("collection", [])
    
    async def get_event(self, event_uuid: str) -> Dict:
        """Get a specific scheduled event."""
        result = await self._request("GET", f"/scheduled_events/{event_uuid}")
        return result.get("resource", {})
    
    async def cancel_event(self, event_uuid: str, reason: Optional[str] = None) -> Dict:
        """
        Cancel a scheduled event.
        
        Args:
            event_uuid: The UUID of the event to cancel
            reason: Optional cancellation reason
            
        Returns:
            Cancellation confirmation
        """
        data = {}
        if reason:
            data["reason"] = reason
            
        result = await self._request(
            "POST",
            f"/scheduled_events/{event_uuid}/cancellation",
            json=data
        )
        return result.get("resource", {})
    
    async def create_single_use_scheduling_link(
        self,
        event_type_uri: str,
        max_event_count: int = 1
    ) -> Dict:
        """
        Create a single-use scheduling link.
        
        Args:
            event_type_uri: The event type URI
            max_event_count: Maximum bookings allowed
            
        Returns:
            Scheduling link details
        """
        data = {
            "max_event_count": max_event_count,
            "owner": event_type_uri,
            "owner_type": "EventType"
        }
        result = await self._request("POST", "/scheduling_links", json=data)
        return result.get("resource", {})


# Initialize client
calendly_client = CalendlyClient()


# Response Models
class CalendlyUser(BaseModel):
    uri: str
    name: str
    email: str
    scheduling_url: str
    timezone: str


class CalendlyEventType(BaseModel):
    uri: str
    name: str
    slug: str
    duration: int
    scheduling_url: str
    active: bool


class CalendlyAvailableTime(BaseModel):
    start_time: str
    status: str
    invitees_remaining: Optional[int] = None


class CalendlyScheduledEvent(BaseModel):
    uri: str
    name: str
    status: str
    start_time: str
    end_time: str
    event_type: str
    location: Optional[Dict] = None
    invitees_counter: Optional[Dict] = None
    created_at: str
    updated_at: str


# API Endpoints

@router.get("/user")
async def get_current_user():
    """Get the current authenticated Calendly user."""
    try:
        user = await calendly_client.get_current_user()
        return {
            "success": True,
            "user": {
                "uri": user.get("uri"),
                "name": user.get("name"),
                "email": user.get("email"),
                "scheduling_url": user.get("scheduling_url"),
                "timezone": user.get("timezone")
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get user: {str(e)}")


@router.get("/event-types")
async def get_event_types():
    """Get all event types for the authenticated user."""
    try:
        event_types = await calendly_client.get_event_types()
        return {
            "success": True,
            "event_types": [
                {
                    "uri": et.get("uri"),
                    "name": et.get("name"),
                    "slug": et.get("slug"),
                    "duration": et.get("duration"),
                    "scheduling_url": et.get("scheduling_url"),
                    "active": et.get("active"),
                    "description": et.get("description_plain")
                }
                for et in event_types
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get event types: {str(e)}")


@router.get("/availability")
async def get_availability(
    event_type_uri: str,
    date: str,
    days: int = 1
):
    """
    Get available times for an event type.
    
    - **event_type_uri**: The URI of the event type
    - **date**: Start date (YYYY-MM-DD)
    - **days**: Number of days to check (default: 1)
    """
    try:
        # Parse date
        start_date = datetime.strptime(date, "%Y-%m-%d")
        end_date = start_date + timedelta(days=days)
        
        # Format as ISO 8601
        start_time = start_date.isoformat() + "Z"
        end_time = end_date.isoformat() + "Z"
        
        available_times = await calendly_client.get_available_times(
            event_type_uri, start_time, end_time
        )
        
        # Group by date
        slots_by_date = {}
        for slot in available_times:
            slot_start = datetime.fromisoformat(slot["start_time"].replace("Z", "+00:00"))
            date_key = slot_start.strftime("%Y-%m-%d")
            
            if date_key not in slots_by_date:
                slots_by_date[date_key] = []
            
            slots_by_date[date_key].append({
                "start_time": slot_start.strftime("%H:%M"),
                "status": slot.get("status", "available"),
                "scheduling_url": slot.get("scheduling_url")
            })
        
        return {
            "success": True,
            "event_type_uri": event_type_uri,
            "date_range": {"start": date, "end": end_date.strftime("%Y-%m-%d")},
            "availability": slots_by_date
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get availability: {str(e)}")


@router.get("/scheduled-events")
async def get_scheduled_events(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    status: str = "active"
):
    """
    Get scheduled events.
    
    - **start_date**: Minimum start date (YYYY-MM-DD)
    - **end_date**: Maximum start date (YYYY-MM-DD)
    - **status**: Event status (active, canceled)
    """
    try:
        min_start = None
        max_start = None
        
        if start_date:
            min_start = datetime.strptime(start_date, "%Y-%m-%d").isoformat() + "Z"
        if end_date:
            max_start = datetime.strptime(end_date, "%Y-%m-%d").isoformat() + "Z"
        
        events = await calendly_client.get_scheduled_events(
            min_start_time=min_start,
            max_start_time=max_start,
            status=status
        )
        
        return {
            "success": True,
            "total": len(events),
            "events": [
                {
                    "uri": e.get("uri"),
                    "name": e.get("name"),
                    "status": e.get("status"),
                    "start_time": e.get("start_time"),
                    "end_time": e.get("end_time"),
                    "event_type": e.get("event_type"),
                    "location": e.get("location"),
                    "created_at": e.get("created_at")
                }
                for e in events
            ]
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get events: {str(e)}")


@router.get("/event/{event_uuid}")
async def get_event(event_uuid: str):
    """Get details of a specific scheduled event."""
    try:
        event = await calendly_client.get_event(event_uuid)
        return {
            "success": True,
            "event": event
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get event: {str(e)}")


@router.post("/cancel/{event_uuid}")
async def cancel_event(event_uuid: str, reason: Optional[str] = None):
    """
    Cancel a scheduled event.
    
    - **event_uuid**: The UUID of the event to cancel
    - **reason**: Optional cancellation reason
    """
    try:
        result = await calendly_client.cancel_event(event_uuid, reason)
        return {
            "success": True,
            "message": "Event cancelled successfully",
            "cancellation": result
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cancel event: {str(e)}")


@router.post("/scheduling-link")
async def create_scheduling_link(event_type_uri: str):
    """
    Create a single-use scheduling link.
    
    This link can be shared with a patient to book a specific appointment.
    """
    try:
        link = await calendly_client.create_single_use_scheduling_link(event_type_uri)
        return {
            "success": True,
            "booking_url": link.get("booking_url"),
            "owner": link.get("owner"),
            "owner_type": link.get("owner_type")
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create scheduling link: {str(e)}")


# Webhook handler for Calendly events
class WebhookPayload(BaseModel):
    event: str
    payload: Dict[str, Any]


@router.post("/webhook")
async def handle_webhook(payload: WebhookPayload):
    """
    Handle Calendly webhook events.
    
    Supported events:
    - invitee.created: New booking
    - invitee.canceled: Booking cancelled
    """
    event_type = payload.event
    data = payload.payload
    
    if event_type == "invitee.created":
        # New booking created
        invitee = data.get("invitee", {})
        scheduled_event = data.get("scheduled_event", {})
        
        print(f"New booking: {invitee.get('name')} - {scheduled_event.get('start_time')}")
        
        return {
            "success": True,
            "message": "Booking recorded",
            "booking": {
                "invitee_name": invitee.get("name"),
                "invitee_email": invitee.get("email"),
                "event_start": scheduled_event.get("start_time"),
                "event_end": scheduled_event.get("end_time")
            }
        }
    
    elif event_type == "invitee.canceled":
        # Booking cancelled
        invitee = data.get("invitee", {})
        
        print(f"Booking cancelled: {invitee.get('name')}")
        
        return {
            "success": True,
            "message": "Cancellation recorded"
        }
    
    return {"success": True, "message": f"Unhandled event type: {event_type}"}
