"""
Medical Appointment Scheduling Agent.
Handles conversation flow, intent detection, and coordinates between tools.
"""

import json
import uuid
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
import os
import asyncio

import google.generativeai as genai

from models.schemas import (
    AppointmentType,
    APPOINTMENT_DURATIONS,
    ConversationPhase,
    ConversationState,
    ChatMessage,
)
from tools.availability_tool import AvailabilityTool, parse_date_reference, parse_time_preference
from tools.booking_tool import BookingTool
from rag.faq_rag import get_faq_rag
from .prompts import (
    SYSTEM_PROMPT,
    INTENT_CLASSIFICATION_PROMPT,
)


class Intent(str, Enum):
    """User intent types."""
    SCHEDULE = "SCHEDULE"
    FAQ = "FAQ"
    RESCHEDULE = "RESCHEDULE"
    CANCEL = "CANCEL"
    PROVIDE_INFO = "PROVIDE_INFO"
    SELECT_SLOT = "SELECT_SLOT"
    CONFIRM = "CONFIRM"
    DECLINE = "DECLINE"
    GREETING = "GREETING"
    OTHER = "OTHER"


class SchedulingAgent:
    """
    Intelligent conversational agent for medical appointment scheduling.
    """
    
    def __init__(self, api_base_url: str = "http://localhost:8000"):
        """
        Initialize the scheduling agent.
        
        Args:
            api_base_url: Base URL for the Calendly API
        """
        self.api_base_url = api_base_url
        self.availability_tool = AvailabilityTool(api_base_url)
        self.booking_tool = BookingTool(api_base_url)
        self.faq_rag = get_faq_rag()
        
        # Initialize Gemini client
        api_key = os.getenv("GOOGLE_API_KEY")
        self.model_name = os.getenv("LLM_MODEL", "gemini-2.5-flash")
        
        if api_key:
            genai.configure(api_key=api_key)
            self.llm_model = genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=SYSTEM_PROMPT
            )
            # Chat sessions for each user session
            self.chat_sessions: Dict[str, Any] = {}
        else:
            self.llm_model = None
            self.chat_sessions = {}
        
        # Session storage (in production, use Redis or database)
        self.sessions: Dict[str, ConversationState] = {}
    
    def get_or_create_session(self, session_id: Optional[str] = None) -> ConversationState:
        """Get existing session or create a new one."""
        if session_id and session_id in self.sessions:
            return self.sessions[session_id]
        
        new_session_id = session_id or str(uuid.uuid4())
        state = ConversationState(session_id=new_session_id)
        self.sessions[new_session_id] = state
        return state
    
    def update_session(self, state: ConversationState) -> None:
        """Update session state."""
        state.updated_at = datetime.now()
        self.sessions[state.session_id] = state
    
    async def classify_intent(self, message: str, current_phase: str) -> Tuple[Intent, Dict]:
        """
        Classify user intent and extract entities.
        
        Args:
            message: User's message
            current_phase: Current conversation phase
            
        Returns:
            Tuple of (intent, extracted_entities)
        """
        # Rule-based intent classification (faster, doesn't require LLM)
        message_lower = message.lower().strip()
        entities = {}
        
        # Greeting detection
        greetings = ["hi", "hello", "hey", "good morning", "good afternoon", "good evening"]
        if any(message_lower.startswith(g) for g in greetings) or message_lower in greetings:
            return Intent.GREETING, entities
        
        # FAQ detection
        faq_keywords = [
            "where", "location", "address", "parking", "directions",
            "insurance", "accept", "payment", "cost", "price", "billing",
            "hours", "open", "close", "when are you",
            "bring", "documents", "prepare", "first visit",
            "cancel", "cancellation policy", "policy",
            "covid", "mask", "protocol",
            "telehealth", "virtual"
        ]
        
        # Check for FAQ intent
        if self.faq_rag.is_faq_question(message):
            # Check if it's actually a cancellation request vs cancellation policy
            if "cancel my" in message_lower or "cancel the" in message_lower:
                return Intent.CANCEL, entities
            return Intent.FAQ, entities
        
        # Scheduling intent
        schedule_keywords = ["schedule", "book", "appointment", "see the doctor", "need to see", "want to see"]
        if any(kw in message_lower for kw in schedule_keywords):
            # Extract date if present
            date = parse_date_reference(message)
            if date:
                entities["date"] = date
            
            # Extract time preference
            time_pref = parse_time_preference(message)
            if time_pref != "any":
                entities["time_preference"] = time_pref
            
            return Intent.SCHEDULE, entities
        
        # Cancel intent
        if "cancel" in message_lower and ("my" in message_lower or "appointment" in message_lower):
            return Intent.CANCEL, entities
        
        # Reschedule intent
        if "reschedule" in message_lower or "change" in message_lower and "appointment" in message_lower:
            return Intent.RESCHEDULE, entities
        
        # Confirm intent
        confirm_words = ["yes", "confirm", "book it", "sounds good", "perfect", "great", "let's do it", "that works"]
        if any(cw in message_lower for cw in confirm_words):
            return Intent.CONFIRM, entities
        
        # Decline intent
        decline_words = ["no", "don't", "won't work", "different", "other", "none of these", "something else"]
        if any(dw in message_lower for dw in decline_words):
            return Intent.DECLINE, entities
        
        # Select slot (check for time patterns)
        time_patterns = [
            r'\d{1,2}:\d{2}',  # 10:00
            r'\d{1,2}\s*(am|pm)',  # 10 am
            r'\d{1,2}:\d{2}\s*(am|pm)',  # 10:00 am
        ]
        for pattern in time_patterns:
            if re.search(pattern, message_lower):
                return Intent.SELECT_SLOT, {"time_selection": message}
        
        # Check for day selection during slot recommendation
        days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", 
                "tomorrow", "today"]
        if current_phase == ConversationPhase.SLOT_RECOMMENDATION.value:
            for day in days:
                if day in message_lower:
                    return Intent.SELECT_SLOT, {"date_selection": message}
        
        # Provide info - detect name, phone, email patterns
        email_pattern = r'[\w\.-]+@[\w\.-]+\.\w+'
        phone_pattern = r'[\d\-\(\)\s\+]{10,}'
        
        if current_phase in [ConversationPhase.COLLECTING_INFO.value, ConversationPhase.CONFIRMATION.value]:
            if re.search(email_pattern, message):
                entities["email"] = re.search(email_pattern, message).group()
                return Intent.PROVIDE_INFO, entities
            if re.search(phone_pattern, message):
                entities["phone"] = re.search(phone_pattern, message).group()
                return Intent.PROVIDE_INFO, entities
            # Assume it might be a name or other info
            return Intent.PROVIDE_INFO, entities
        
        # Default
        return Intent.OTHER, entities
    
    async def generate_response(
        self,
        messages: List[Dict],
        system_prompt: Optional[str] = None
    ) -> str:
        """
        Generate a response using the LLM.
        
        Args:
            messages: Conversation messages
            system_prompt: Optional system prompt override
            
        Returns:
            Generated response text
        """
        if not self.llm_model:
            # Fallback for when LLM is not available
            return self._generate_fallback_response(messages)
        
        try:
            # Convert messages to Gemini format
            gemini_messages = []
            for msg in messages:
                role = "user" if msg["role"] == "user" else "model"
                gemini_messages.append({
                    "role": role,
                    "parts": [msg["content"]]
                })
            
            # Create a chat session with custom system instruction if provided
            if system_prompt and system_prompt != SYSTEM_PROMPT:
                model = genai.GenerativeModel(
                    model_name=self.model_name,
                    system_instruction=system_prompt
                )
            else:
                model = self.llm_model
            
            # Use async wrapper for Gemini
            response = await asyncio.to_thread(
                lambda: model.generate_content(
                    gemini_messages,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.7,
                        max_output_tokens=500
                    )
                )
            )
            
            return response.text
        except Exception as e:
            print(f"LLM error: {e}")
            return self._generate_fallback_response(messages)
    
    async def chat_with_gemini(
        self,
        message: str,
        session_id: str,
        context: Optional[str] = None
    ) -> str:
        """
        Chat with Gemini using conversation history.
        
        Args:
            message: User's message
            session_id: Session ID for conversation continuity
            context: Optional context to include (e.g., FAQ answer, availability)
            
        Returns:
            Generated response text
        """
        if not self.llm_model:
            return self._generate_fallback_response([{"role": "user", "content": message}])
        
        try:
            # Get or create chat session for this user
            if session_id not in self.chat_sessions:
                self.chat_sessions[session_id] = self.llm_model.start_chat(history=[])
            
            chat = self.chat_sessions[session_id]
            
            # Include context if provided
            prompt = message
            if context:
                prompt = f"[CONTEXT: {context}]\n\nUser message: {message}"
            
            # Generate response
            response = await asyncio.to_thread(
                lambda: chat.send_message(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.7,
                        max_output_tokens=500
                    )
                )
            )
            
            return response.text
        except Exception as e:
            print(f"Gemini chat error: {e}")
            return self._generate_fallback_response([{"role": "user", "content": message}])
    
    def _generate_fallback_response(self, messages: List[Dict]) -> str:
        """Generate a fallback response when LLM is unavailable."""
        return "I'd be happy to help you schedule an appointment or answer questions about our clinic. What can I help you with today?"
    
    async def process_message(
        self,
        message: str,
        session_id: Optional[str] = None
    ) -> Dict:
        """
        Process a user message and generate a response using Gemini.
        
        Args:
            message: User's message
            session_id: Optional session ID for conversation continuity
            
        Returns:
            Dictionary with response and session info
        """
        # Get or create session
        state = self.get_or_create_session(session_id)
        
        # Add user message to history
        state.messages.append(ChatMessage(
            role="user",
            content=message,
            timestamp=datetime.now()
        ))
        
        # Classify intent
        intent, entities = await self.classify_intent(message, state.phase.value)
        
        # Build context based on intent
        context = await self._build_context_for_intent(intent, entities, message, state)
        
        # Get response from Gemini with context
        response = await self.chat_with_gemini(message, state.session_id, context)
        
        # Update state based on intent (for tracking conversation flow)
        await self._update_state_for_intent(intent, entities, message, state)
        
        # Add assistant message to history
        state.messages.append(ChatMessage(
            role="assistant",
            content=response,
            timestamp=datetime.now()
        ))
        
        # Update session
        self.update_session(state)
        
        return {
            "message": response,
            "session_id": state.session_id,
            "intent": intent.value,
            "phase": state.phase.value,
            "booking_status": self._get_booking_status(state)
        }
    
    async def _build_context_for_intent(
        self,
        intent: Intent,
        entities: Dict,
        message: str,
        state: ConversationState
    ) -> str:
        """Build context string for Gemini based on intent and state."""
        
        context_parts = []
        
        # Add current conversation phase
        context_parts.append(f"Current conversation phase: {state.phase.value}")
        
        if intent == Intent.GREETING:
            context_parts.append(
                "The user is greeting. Welcome them warmly to HealthCare Plus Clinic. "
                "Offer to help with scheduling appointments or answering questions."
            )
        
        elif intent == Intent.FAQ:
            # Get FAQ answer from RAG
            faq_answer = self.faq_rag.format_answer_for_chat(message)
            context_parts.append(f"FAQ Information from knowledge base:\n{faq_answer}")
            context_parts.append("Answer the user's question based on this information. Be helpful and concise.")
            
            if state.phase in [ConversationPhase.UNDERSTANDING_NEEDS, ConversationPhase.COLLECTING_PREFERENCES, 
                              ConversationPhase.SLOT_RECOMMENDATION, ConversationPhase.COLLECTING_INFO]:
                context_parts.append("After answering, offer to continue with their appointment scheduling.")
        
        elif intent == Intent.SCHEDULE:
            context_parts.append(
                "The user wants to schedule an appointment. "
                "Ask about the reason for their visit to determine the appropriate appointment type."
            )
            if entities.get("date"):
                context_parts.append(f"User mentioned date preference: {entities['date']}")
            if entities.get("time_preference"):
                context_parts.append(f"User mentioned time preference: {entities['time_preference']}")
        
        elif intent == Intent.PROVIDE_INFO:
            # User is providing information during booking
            if state.phase == ConversationPhase.UNDERSTANDING_NEEDS:
                context_parts.append(
                    f"User provided reason for visit: '{message}'. "
                    "Acknowledge this and recommend an appropriate appointment type, then ask for date/time preference."
                )
            elif state.phase == ConversationPhase.COLLECTING_INFO:
                collected = state.patient_info or {}
                missing = []
                if not collected.get("name"):
                    missing.append("name")
                if not collected.get("phone"):
                    missing.append("phone number")
                if not collected.get("email"):
                    missing.append("email address")
                
                if missing:
                    context_parts.append(f"Still need to collect: {', '.join(missing)}. Ask for the next missing item.")
                else:
                    # All info collected, show confirmation
                    slot = state.selected_slot or {}
                    context_parts.append(
                        f"All information collected! Show confirmation summary:\n"
                        f"- Date: {slot.get('date', 'TBD')}\n"
                        f"- Time: {slot.get('start_time', 'TBD')}\n"
                        f"- Name: {collected.get('name')}\n"
                        f"- Phone: {collected.get('phone')}\n"
                        f"- Email: {collected.get('email')}\n"
                        f"- Reason: {state.reason_for_visit}\n"
                        "Ask if they want to confirm the booking."
                    )
        
        elif intent == Intent.SELECT_SLOT:
            # User selecting a time slot
            context_parts.append(
                "User is selecting a time slot. Confirm their choice and ask for their contact information "
                "(name first, then phone, then email)."
            )
        
        elif intent == Intent.CONFIRM:
            if state.phase == ConversationPhase.CONFIRMATION:
                # Book the appointment using mock Calendly
                slot = state.selected_slot or {}
                patient_info = state.patient_info or {}
                
                result = await self.booking_tool.book_appointment(
                    appointment_type=state.appointment_type.value if state.appointment_type else "consultation",
                    date=slot.get("date", ""),
                    start_time=slot.get("start_time", ""),
                    patient_name=patient_info.get("name", ""),
                    patient_email=patient_info.get("email", ""),
                    patient_phone=patient_info.get("phone", ""),
                    reason=state.reason_for_visit or "General consultation"
                )
                
                if result.get("success"):
                    state.phase = ConversationPhase.COMPLETED
                    booking_info = self.booking_tool.format_confirmation_message(result)
                    context_parts.append(
                        f"BOOKING SUCCESSFUL! Here are the details:\n{booking_info}\n\n"
                        "Provide a warm confirmation message with the booking details. "
                        "Remind them what to bring and mention the cancellation policy."
                    )
                else:
                    context_parts.append(
                        f"Booking failed: {result.get('error', 'Unknown error')}. "
                        "Apologize and offer to try a different time or call the office."
                    )
            elif state.phase == ConversationPhase.COLLECTING_PREFERENCES:
                context_parts.append("User confirmed the appointment type. Now ask for their preferred date and time.")
        
        elif intent == Intent.DECLINE:
            if state.phase == ConversationPhase.SLOT_RECOMMENDATION:
                context_parts.append("User declined the offered slots. Offer to check different dates or times.")
            elif state.phase == ConversationPhase.CONFIRMATION:
                context_parts.append("User wants to change something. Ask what they'd like to modify.")
            else:
                context_parts.append("User declined. Ask how else you can help.")
        
        elif intent == Intent.CANCEL:
            context_parts.append(
                "User wants to cancel an appointment. Ask for their booking ID or confirmation code "
                "to proceed with cancellation."
            )
        
        elif intent == Intent.RESCHEDULE:
            context_parts.append(
                "User wants to reschedule. Ask for their booking ID and then help find a new time."
            )
        
        else:  # OTHER / Unknown
            if state.phase == ConversationPhase.UNDERSTANDING_NEEDS:
                context_parts.append(
                    f"User said: '{message}'. This might be their reason for visit. "
                    "Acknowledge and recommend an appointment type."
                )
            elif state.phase == ConversationPhase.COLLECTING_PREFERENCES:
                # Check if they mentioned date/time
                date = parse_date_reference(message)
                time_pref = parse_time_preference(message)
                
                if date or time_pref != "any":
                    # Get available slots from mock Calendly
                    result = await self.availability_tool.get_available_slots(
                        date or datetime.now().strftime("%Y-%m-%d"),
                        state.appointment_type.value if state.appointment_type else "consultation"
                    )
                    
                    if result.get("success"):
                        slots = result.get("available_slots", [])[:5]
                        if slots:
                            slots_text = ", ".join([s["start_time"] for s in slots])
                            context_parts.append(
                                f"Available slots for {date or 'today'}: {slots_text}\n"
                                "Present these options in a friendly way and ask which works best."
                            )
                        else:
                            # Get alternative dates
                            alt_result = await self.availability_tool.get_available_dates(14, 
                                state.appointment_type.value if state.appointment_type else "consultation")
                            alt_dates = alt_result.get("available_dates", [])[:3]
                            if alt_dates:
                                alt_text = ", ".join([f"{d['day_name']} {d['date']}" for d in alt_dates])
                                context_parts.append(
                                    f"No slots on requested date. Alternative dates: {alt_text}. "
                                    "Offer these alternatives."
                                )
                else:
                    context_parts.append("Ask about their preferred date and time (morning/afternoon).")
            else:
                context_parts.append(
                    "Not sure what the user wants. Politely ask how you can help with "
                    "scheduling, questions about the clinic, or managing existing appointments."
                )
        
        return "\n".join(context_parts)
    
    async def _update_state_for_intent(
        self,
        intent: Intent,
        entities: Dict,
        message: str,
        state: ConversationState
    ) -> None:
        """Update conversation state based on intent."""
        
        if intent == Intent.GREETING:
            state.phase = ConversationPhase.GREETING
        
        elif intent == Intent.SCHEDULE:
            state.phase = ConversationPhase.UNDERSTANDING_NEEDS
            if entities.get("date"):
                state.preferred_date = entities["date"]
            if entities.get("time_preference"):
                state.preferred_time_of_day = entities["time_preference"]
        
        elif intent == Intent.PROVIDE_INFO:
            if state.phase == ConversationPhase.UNDERSTANDING_NEEDS:
                state.reason_for_visit = message
                # Infer appointment type
                reason_lower = message.lower()
                if any(kw in reason_lower for kw in ["follow up", "follow-up", "results", "medication"]):
                    state.appointment_type = AppointmentType.FOLLOW_UP
                elif any(kw in reason_lower for kw in ["physical", "annual", "checkup", "check-up"]):
                    state.appointment_type = AppointmentType.PHYSICAL_EXAM
                elif any(kw in reason_lower for kw in ["specialist", "complex", "detailed"]):
                    state.appointment_type = AppointmentType.SPECIALIST_CONSULTATION
                else:
                    state.appointment_type = AppointmentType.GENERAL_CONSULTATION
                state.phase = ConversationPhase.COLLECTING_PREFERENCES
            
            elif state.phase == ConversationPhase.COLLECTING_INFO:
                if state.patient_info is None:
                    state.patient_info = {}
                
                # Extract info from message
                email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', message)
                phone_match = re.search(r'[\d\-\(\)\s\+]{10,}', message)
                
                if email_match:
                    state.patient_info["email"] = email_match.group()
                elif phone_match:
                    state.patient_info["phone"] = phone_match.group().strip()
                elif not state.patient_info.get("name"):
                    state.patient_info["name"] = message.strip()
                
                # Check if all info collected
                if all(state.patient_info.get(k) for k in ["name", "phone", "email"]):
                    state.phase = ConversationPhase.CONFIRMATION
        
        elif intent == Intent.SELECT_SLOT:
            # Parse slot selection
            selected = self._parse_slot_selection(message, state)
            if selected:
                state.selected_slot = selected
                state.phase = ConversationPhase.COLLECTING_INFO
        
        elif intent == Intent.CONFIRM:
            if state.phase == ConversationPhase.COLLECTING_PREFERENCES:
                state.phase = ConversationPhase.SLOT_RECOMMENDATION
        
        elif intent == Intent.OTHER:
            if state.phase == ConversationPhase.UNDERSTANDING_NEEDS:
                state.reason_for_visit = message
                state.appointment_type = AppointmentType.GENERAL_CONSULTATION
                state.phase = ConversationPhase.COLLECTING_PREFERENCES
            elif state.phase == ConversationPhase.COLLECTING_PREFERENCES:
                date = parse_date_reference(message)
                time_pref = parse_time_preference(message)
                if date:
                    state.preferred_date = date
                if time_pref != "any":
                    state.preferred_time_of_day = time_pref
                if date or time_pref != "any":
                    state.phase = ConversationPhase.SLOT_RECOMMENDATION
    
    def _parse_slot_selection(self, message: str, state: ConversationState) -> Optional[Dict]:
        """Parse user's slot selection and match to available slots."""
        message_lower = message.lower()
        
        # Check for day names
        days_map = {
            "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
            "friday": 4, "saturday": 5, "sunday": 6,
            "tomorrow": None, "today": None
        }
        
        selected_date = state.preferred_date
        selected_time = None
        
        # Extract day
        for day_name in days_map.keys():
            if day_name in message_lower:
                if day_name == "today":
                    selected_date = datetime.now().strftime("%Y-%m-%d")
                elif day_name == "tomorrow":
                    from datetime import timedelta
                    selected_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
                else:
                    selected_date = parse_date_reference(day_name)
                break
        
        # Extract time
        time_patterns = [
            (r'(\d{1,2}):(\d{2})\s*(am|pm)?', lambda m: self._normalize_time(m.group(1), m.group(2), m.group(3))),
            (r'(\d{1,2})\s*(am|pm)', lambda m: self._normalize_time(m.group(1), "00", m.group(2))),
        ]
        
        for pattern, normalizer in time_patterns:
            match = re.search(pattern, message_lower)
            if match:
                selected_time = normalizer(match)
                break
        
        if selected_date and selected_time:
            return {"date": selected_date, "start_time": selected_time}
        elif selected_date:
            return {"date": selected_date, "start_time": selected_time}
        
        return None
    
    def _normalize_time(self, hour: str, minute: str, ampm: Optional[str]) -> str:
        """Normalize time to 24-hour format."""
        h = int(hour)
        m = int(minute)
        
        if ampm:
            ampm = ampm.lower()
            if ampm == "pm" and h != 12:
                h += 12
            elif ampm == "am" and h == 12:
                h = 0
        
        return f"{h:02d}:{m:02d}"
    
    def _get_booking_status(self, state: ConversationState) -> Optional[Dict]:
        """Get current booking status for response."""
        if state.phase == ConversationPhase.COMPLETED and state.selected_slot:
            return {
                "status": "completed",
                "date": state.selected_slot.get("date"),
                "time": state.selected_slot.get("start_time")
            }
        elif state.selected_slot:
            return {
                "status": "in_progress",
                "phase": state.phase.value,
                "date": state.selected_slot.get("date"),
                "time": state.selected_slot.get("start_time")
            }
        return None
                    formatted_time = time_str
                
                duration = APPOINTMENT_DURATIONS.get(state.appointment_type, 30)
                
                context = (
                    f"The user selected an appointment slot: {formatted_date} at {formatted_time} "
                    f"for a {duration}-minute appointment. Confirm this is a great choice and "
                    f"ask for their full name to proceed with booking. Be friendly and professional."
                )
                
                return await self.chat_with_gemini(
                    message,
                    state.session_id,
                    context
                )
            else:
                context = (
                    "The user's slot selection couldn't be matched to available options. "
                    "Politely ask them to select one of the previously mentioned times "
                    "or offer to show different options."
                )
                
                return await self.chat_with_gemini(
                    message,
                    state.session_id,
                    context
                )
        
        return await self._handle_unknown(message, state)
    
    def _parse_slot_selection(self, message: str, state: ConversationState) -> Optional[Dict]:
        """Parse user's slot selection and match to available slots."""
        message_lower = message.lower()
        
        # Get stored available slots from state or recent context
        # For now, extract date and time from message
        
        # Check for day names
        days_map = {
            "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
            "friday": 4, "saturday": 5, "sunday": 6,
            "tomorrow": None, "today": None
        }
        
        selected_date = state.preferred_date
        selected_time = None
        
        # Extract day
        for day_name in days_map.keys():
            if day_name in message_lower:
                if day_name == "today":
                    selected_date = datetime.now().strftime("%Y-%m-%d")
                elif day_name == "tomorrow":
                    selected_date = (datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + 
                                   __import__('datetime').timedelta(days=1)).strftime("%Y-%m-%d")
                else:
                    # Calculate the date for the given day name
                    selected_date = parse_date_reference(day_name)
                break
        
        # Extract time
        time_patterns = [
            (r'(\d{1,2}):(\d{2})\s*(am|pm)?', lambda m: self._normalize_time(m.group(1), m.group(2), m.group(3))),
            (r'(\d{1,2})\s*(am|pm)', lambda m: self._normalize_time(m.group(1), "00", m.group(2))),
        ]
        
        for pattern, normalizer in time_patterns:
            match = re.search(pattern, message_lower)
            if match:
                selected_time = normalizer(match)
                break
        
        if selected_date and selected_time:
            return {
                "date": selected_date,
                "start_time": selected_time
            }
        elif selected_date:
            # If only date is selected, might need more info
            return {
                "date": selected_date,
                "start_time": selected_time
            }
        
        return None
    
    def _normalize_time(self, hour: str, minute: str, ampm: Optional[str]) -> str:
        """Normalize time to 24-hour format."""
        h = int(hour)
        m = int(minute)
        
        if ampm:
            ampm = ampm.lower()
            if ampm == "pm" and h != 12:
                h += 12
            elif ampm == "am" and h == 12:
                h = 0
        
        return f"{h:02d}:{m:02d}"
    
    async def _handle_info_provided(
        self,
        entities: Dict,
        message: str,
        state: ConversationState
    ) -> str:
        """Handle when user provides information."""
        if state.phase != ConversationPhase.COLLECTING_INFO:
            return await self._handle_unknown(message, state)
        
        # Initialize patient_info if needed
        if state.patient_info is None:
            state.patient_info = {}
        
        # Update with extracted entities
        if entities.get("email"):
            state.patient_info["email"] = entities["email"]
        elif entities.get("phone"):
            state.patient_info["phone"] = entities["phone"]
        else:
            # Check for email in message
            email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', message)
            if email_match:
                state.patient_info["email"] = email_match.group()
            # Check for phone in message
            elif re.search(r'[\d\-\(\)\s\+]{10,}', message):
                phone_match = re.search(r'[\d\-\(\)\s\+]{10,}', message)
                state.patient_info["phone"] = phone_match.group().strip()
            # Assume it's a name if we don't have one
            elif not state.patient_info.get("name"):
                state.patient_info["name"] = message.strip()
        
        # Check what's still missing
        missing = []
        if not state.patient_info.get("name"):
            missing.append("name")
        if not state.patient_info.get("phone"):
            missing.append("phone number")
        if not state.patient_info.get("email"):
            missing.append("email address")
        
        if missing:
            context = (
                f"The user just provided some of their information. We still need: {', '.join(missing)}. "
                f"Thank them and ask for the missing information in a friendly way."
            )
            return await self.chat_with_gemini(
                message,
                state.session_id,
                context
            )
        
        # All info collected - move to confirmation
        state.phase = ConversationPhase.CONFIRMATION
        
        slot = state.selected_slot or {}
        date_str = slot.get("date", "")
        time_str = slot.get("start_time", "")
        
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            formatted_date = date_obj.strftime("%A, %B %d, %Y")
            time_obj = datetime.strptime(time_str, "%H:%M")
            formatted_time = time_obj.strftime("%I:%M %p").lstrip("0")
        except ValueError:
            formatted_date = date_str
            formatted_time = time_str
        
        appt_type = state.appointment_type.value if state.appointment_type else "consultation"
        duration = APPOINTMENT_DURATIONS.get(state.appointment_type, 30)
        
        context = (
            f"All patient information collected. Present a confirmation summary with these details:\n"
            f"- Date: {formatted_date}\n"
            f"- Time: {formatted_time}\n"
            f"- Duration: {duration} minutes\n"
            f"- Name: {state.patient_info.get('name', 'N/A')}\n"
            f"- Phone: {state.patient_info.get('phone', 'N/A')}\n"
            f"- Email: {state.patient_info.get('email', 'N/A')}\n"
            f"- Reason: {state.reason_for_visit or 'General consultation'}\n\n"
            f"Use emojis for visual appeal (📅🕐⏱️👤📞📧📋) and ask if they'd like to confirm the booking."
        )
        
        return await self.chat_with_gemini(
            message,
            state.session_id,
            context
        )
    
    async def _handle_confirmation(self, state: ConversationState) -> str:
        """Handle booking confirmation using Gemini."""
        if state.phase != ConversationPhase.CONFIRMATION:
            # User might be confirming appointment type or other things
            if state.phase == ConversationPhase.COLLECTING_PREFERENCES:
                return await self._ask_for_date_preference(state)
            
            context = "The user said something affirmative. Ask what they'd like to confirm."
            return await self.chat_with_gemini("yes", state.session_id, context)
        
        # Book the appointment (using mock Calendly API)
        slot = state.selected_slot or {}
        patient_info = state.patient_info or {}
        
        result = await self.booking_tool.book_appointment(
            appointment_type=state.appointment_type.value if state.appointment_type else "consultation",
            date=slot.get("date", ""),
            start_time=slot.get("start_time", ""),
            patient_name=patient_info.get("name", ""),
            patient_email=patient_info.get("email", ""),
            patient_phone=patient_info.get("phone", ""),
            reason=state.reason_for_visit or "General consultation"
        )
        
        if result.get("success"):
            state.phase = ConversationPhase.COMPLETED
            
            # Use Gemini to create a warm confirmation message
            booking_details = self.booking_tool.format_confirmation_message(result)
            context = (
                f"The appointment was successfully booked! Here are the details:\n\n{booking_details}\n\n"
                f"Create a warm, professional confirmation message. Include the booking confirmation number "
                f"and remind them about any preparation needed. Wish them well."
            )
            
            return await self.chat_with_gemini(
                "confirm my booking",
                state.session_id,
                context
            )
        else:
            context = (
                f"There was an error booking the appointment: {result.get('error', 'Unknown error')}. "
                f"Apologize for the inconvenience and offer alternatives like trying a different time "
                f"or calling the office at +1-555-123-4567."
            )
            
            return await self.chat_with_gemini(
                "booking failed",
                state.session_id,
                context
            )
    
    async def _ask_for_date_preference(self, state: ConversationState) -> str:
        """Ask user for their date and time preferences using Gemini."""
        state.phase = ConversationPhase.COLLECTING_PREFERENCES
        
        context = (
            "The user has confirmed their appointment type. Now ask about their preferred date and time. "
            "Ask if they prefer morning or afternoon, and if they have a specific date in mind or want earliest availability. "
            "Keep it conversational and friendly."
        )
        
        return await self.chat_with_gemini(
            "when can I come in",
            state.session_id,
            context
        )
    
    async def _handle_decline(self, state: ConversationState) -> str:
        """Handle when user declines options using Gemini."""
        if state.phase == ConversationPhase.SLOT_RECOMMENDATION:
            context = (
                "The user declined the offered time slots. Offer to check different dates "
                "or ask if they have a specific day/time preference. Be understanding and helpful."
            )
        elif state.phase == ConversationPhase.CONFIRMATION:
            context = (
                "The user doesn't want to confirm the appointment as is. "
                "Ask if they'd like to change any details or start over with a different time. "
                "Be accommodating."
            )
        else:
            context = "The user declined something. Ask how else you can help them today."
        
        return await self.chat_with_gemini(
            "no",
            state.session_id,
            context
        )
    
    async def _handle_cancel_request(self, message: str, state: ConversationState) -> str:
        """Handle appointment cancellation request using Gemini."""
        context = (
            "The user wants to cancel their appointment. Explain that you need their booking ID "
            "or confirmation code (found in their confirmation email) to proceed. "
            "Be empathetic and professional."
        )
        
        return await self.chat_with_gemini(
            message,
            state.session_id,
            context
        )
    
    async def _handle_reschedule_request(self, message: str, state: ConversationState) -> str:
        """Handle appointment rescheduling request using Gemini."""
        context = (
            "The user wants to reschedule their appointment. Explain that you need their booking ID "
            "or confirmation code, then you can help find a new time. Be helpful and understanding."
        )
        
        return await self.chat_with_gemini(
            message,
            state.session_id,
            context
        )
    
    async def _handle_unknown(self, message: str, state: ConversationState) -> str:
        """Handle unknown or ambiguous intent using Gemini."""
        # Check if it might be continuing a previous topic
        if state.phase == ConversationPhase.UNDERSTANDING_NEEDS:
            # Assume they're providing reason for visit
            state.reason_for_visit = message
            return await self._ask_appointment_type(state)
        
        elif state.phase == ConversationPhase.COLLECTING_PREFERENCES:
            # Try to extract date/time preferences
            date = parse_date_reference(message)
            time_pref = parse_time_preference(message)
            
            if date:
                state.preferred_date = date
            if time_pref != "any":
                state.preferred_time_of_day = time_pref
            
            if date or time_pref != "any":
                return await self._show_available_slots(state)
        
        # Use Gemini for a helpful response
        context = (
            "The user's intent wasn't clear. Politely explain that you can help with:\n"
            "- Scheduling new appointments\n"
            "- Answering questions about the clinic (insurance, hours, location, etc.)\n"
            "- Rescheduling or canceling existing appointments\n\n"
            "Ask how you can assist them. Keep it friendly and brief."
        )
        
        return await self.chat_with_gemini(
            message,
            state.session_id,
            context
        )
    
    async def _show_available_slots(self, state: ConversationState) -> str:
        """Fetch and display available slots using Gemini."""
        state.phase = ConversationPhase.SLOT_RECOMMENDATION
        
        date = state.preferred_date or datetime.now().strftime("%Y-%m-%d")
        appt_type = state.appointment_type.value if state.appointment_type else "consultation"
        
        # Get availability from mock Calendly API
        result = await self.availability_tool.get_available_slots(date, appt_type)
        
        if not result.get("success"):
            context = (
                "There was an issue checking availability. Apologize for the inconvenience "
                "and suggest trying again or calling the office at +1-555-123-4567."
            )
            return await self.chat_with_gemini("check availability", state.session_id, context)
        
        available_slots = result.get("available_slots", [])
        
        # Filter by time preference if specified
        if state.preferred_time_of_day:
            filtered = self.availability_tool.get_slots_for_time_preference(
                available_slots, state.preferred_time_of_day
            )
            if filtered:
                available_slots = filtered
        
        if not available_slots:
            # Get alternative dates from mock Calendly API
            alt_result = await self.availability_tool.get_available_dates(14, appt_type)
            alt_dates = alt_result.get("available_dates", [])[:5]
            
            if alt_dates:
                alt_text = "\n".join([
                    f"- {d['day_name']}, {d['date']} ({d['available_slots']} slots available)"
                    for d in alt_dates
                ])
                context = (
                    f"No slots available on {date} matching the user's preferences. "
                    f"Here are alternative dates:\n{alt_text}\n\n"
                    f"Present these alternatives in a friendly way and ask which works for them."
                )
            else:
                context = (
                    "No appointments available in the next two weeks. "
                    "Apologize and suggest calling +1-555-123-4567 to join a waitlist."
                )
            
            return await self.chat_with_gemini("no availability", state.session_id, context)
        
        # Format slots for display (show up to 5)
        display_slots = available_slots[:5]
        
        try:
            date_obj = datetime.strptime(date, "%Y-%m-%d")
            formatted_date = date_obj.strftime("%A, %B %d")
        except ValueError:
            formatted_date = date
        
        slots_text = []
        for slot in display_slots:
            try:
                time_obj = datetime.strptime(slot["start_time"], "%H:%M")
                formatted_time = time_obj.strftime("%I:%M %p").lstrip("0")
            except ValueError:
                formatted_time = slot["start_time"]
            slots_text.append(formatted_time)
        
        time_pref_text = state.preferred_time_of_day if state.preferred_time_of_day else "any"
        
        context = (
            f"Available slots for {formatted_date} ({time_pref_text} preference):\n"
            f"- {', '.join(slots_text)}\n\n"
            f"Present these time options in a friendly, conversational way "
            f"and ask which time works best for the user."
        )
        
        return await self.chat_with_gemini(
            f"show me availability for {formatted_date}",
            state.session_id,
            context
        )
    
    def _get_booking_status(self, state: ConversationState) -> Optional[Dict]:
        """Get current booking status for response."""
        if state.phase == ConversationPhase.COMPLETED and state.selected_slot:
            return {
                "status": "completed",
                "date": state.selected_slot.get("date"),
                "time": state.selected_slot.get("start_time")
            }
        elif state.selected_slot:
            return {
                "status": "in_progress",
                "phase": state.phase.value,
                "date": state.selected_slot.get("date"),
                "time": state.selected_slot.get("start_time")
            }
        return None
