"""
Medical Appointment Scheduling Agent.
Handles conversation flow, intent detection, and coordinates between tools.
"""

import json
import uuid
import re
from datetime import datetime, timedelta
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
        
        # Check for time selection (when user mentions specific times like "1:30 AM", "12:00", etc.)
        # This should be handled before other intents when we're in slot recommendation phase
        time_pattern = r'\d{1,2}:\d{2}\s*(am|pm)?|\d{1,2}\s*(am|pm)'
        if re.search(time_pattern, message_lower, re.IGNORECASE):
            # User is selecting a specific time
            if current_phase in ["slot_recommendation", "collecting_preferences"]:
                return Intent.SELECT_SLOT, entities
        
        # Check for "earliest" or "available slots" - user wants to see slots
        availability_keywords = ["earliest", "available slots", "available", "slots", "what times", "when can"]
        if any(kw in message_lower for kw in availability_keywords):
            # This means user wants to see available slots
            date = parse_date_reference(message)
            if date:
                entities["date"] = date
            time_pref = parse_time_preference(message)
            if time_pref != "any":
                entities["time_preference"] = time_pref
            return Intent.SELECT_SLOT, entities
        
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
        
        # Scheduling intent - explicit keywords
        schedule_keywords = ["schedule", "book", "appointment", "see the doctor", "need to see", "want to see", "scheduling"]
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
        
        # Medical symptoms that imply scheduling need
        symptom_keywords = ["pain", "headache", "migraine", "fever", "sick", "hurt", "ache", 
                          "sore", "cough", "cold", "flu", "nausea", "dizzy", "tired",
                          "chest pain", "stomach", "throat", "symptoms"]
        if any(kw in message_lower for kw in symptom_keywords):
            # User is describing symptoms - treat as scheduling request
            entities["reason"] = message
            return Intent.SCHEDULE, entities
        
        # Cancel intent
        if "cancel" in message_lower and ("my" in message_lower or "appointment" in message_lower):
            return Intent.CANCEL, entities
        
        # Reschedule intent
        if "reschedule" in message_lower or "change" in message_lower and "appointment" in message_lower:
            return Intent.RESCHEDULE, entities
        
        # Confirm intent - short affirmative responses
        confirm_words = ["yes", "yea", "yeah", "yep", "yup", "confirm", "book it", "sounds good", "perfect", "great", "let's do it", "that works", "ok", "okay", "sure", "right", "correct", "this is right"]
        if any(message_lower == cw or message_lower.startswith(cw + " ") or message_lower.startswith(cw + ",") for cw in confirm_words):
            return Intent.CONFIRM, entities
        
        # Decline intent
        decline_words = ["no", "nope", "don't", "won't work", "different", "other", "none of these", "something else"]
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
        Process a user message and generate a response.
        
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
        
        # Handle based on intent and phase
        response = await self._handle_intent(intent, entities, message, state)
        
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
    
    async def _handle_intent(
        self,
        intent: Intent,
        entities: Dict,
        message: str,
        state: ConversationState
    ) -> str:
        """Handle user intent based on conversation phase."""
        
        if intent == Intent.GREETING:
            return await self._handle_greeting(state)
        
        elif intent == Intent.FAQ:
            return await self._handle_faq(message, state)
        
        elif intent == Intent.SCHEDULE:
            return await self._handle_schedule_request(entities, message, state)
        
        elif intent == Intent.SELECT_SLOT:
            return await self._handle_slot_selection(entities, message, state)
        
        elif intent == Intent.PROVIDE_INFO:
            return await self._handle_info_provided(entities, message, state)
        
        elif intent == Intent.CONFIRM:
            return await self._handle_confirmation(state)
        
        elif intent == Intent.DECLINE:
            return await self._handle_decline(state)
        
        elif intent == Intent.CANCEL:
            return await self._handle_cancel_request(message, state)
        
        elif intent == Intent.RESCHEDULE:
            return await self._handle_reschedule_request(message, state)
        
        else:
            return await self._handle_unknown(message, state)
    
    async def _handle_greeting(self, state: ConversationState) -> str:
        """Handle greeting intent using Gemini."""
        state.phase = ConversationPhase.GREETING
        
        context = (
            "The user is greeting us. Welcome them warmly to HealthCare Plus Clinic. "
            "Offer to help with scheduling appointments or answering questions about the clinic. "
            "Keep the response friendly and concise (2-3 sentences max)."
        )
        
        return await self.chat_with_gemini(
            "Hi",
            state.session_id,
            context
        )
    
    async def _handle_faq(self, message: str, state: ConversationState) -> str:
        """Handle FAQ questions using RAG + Gemini."""
        # Store current phase if we're in the middle of scheduling
        was_scheduling = state.phase in [
            ConversationPhase.UNDERSTANDING_NEEDS,
            ConversationPhase.COLLECTING_PREFERENCES,
            ConversationPhase.SLOT_RECOMMENDATION,
            ConversationPhase.COLLECTING_INFO,
        ]
        
        if was_scheduling:
            state.pending_faq = True
        
        # Get answer from RAG
        rag_answer = self.faq_rag.format_answer_for_chat(message)
        
        # Use Gemini to provide a natural response based on RAG context
        context = (
            f"The user is asking a question about our clinic. Here's the relevant information from our knowledge base:\n\n"
            f"{rag_answer}\n\n"
            f"Please provide a helpful, friendly response based on this information. "
            f"Keep it concise and conversational."
        )
        
        if was_scheduling:
            context += " Also, offer to continue with scheduling their appointment."
        
        return await self.chat_with_gemini(
            message,
            state.session_id,
            context
        )
    
    async def _handle_schedule_request(
        self,
        entities: Dict,
        message: str,
        state: ConversationState
    ) -> str:
        """Handle new appointment scheduling request using Gemini."""
        state.phase = ConversationPhase.UNDERSTANDING_NEEDS
        
        # Check if reason is already provided
        if entities.get("reason") or self._extract_reason(message):
            state.reason_for_visit = entities.get("reason") or self._extract_reason(message)
            return await self._ask_appointment_type(state)
        
        context = (
            "The user wants to schedule an appointment. Ask them about the reason for their visit "
            "in a friendly, professional manner. Keep it brief (1-2 sentences)."
        )
        
        return await self.chat_with_gemini(
            message,
            state.session_id,
            context
        )
    
    def _extract_reason(self, message: str) -> Optional[str]:
        """Extract reason for visit from message."""
        reason_keywords = ["headache", "checkup", "check-up", "check up", "physical", 
                         "follow up", "follow-up", "sick", "pain", "symptoms"]
        message_lower = message.lower()
        for keyword in reason_keywords:
            if keyword in message_lower:
                return message
        return None
    
    async def _ask_appointment_type(self, state: ConversationState) -> str:
        """Ask about appointment type based on reason using Gemini."""
        reason = state.reason_for_visit or ""
        
        # Infer appointment type from reason
        if any(kw in reason.lower() for kw in ["follow up", "follow-up", "results", "medication"]):
            suggestion = "Follow-up (15 minutes)"
            state.appointment_type = AppointmentType.FOLLOW_UP
        elif any(kw in reason.lower() for kw in ["physical", "annual", "checkup", "check-up"]):
            suggestion = "Physical Exam (45 minutes)"
            state.appointment_type = AppointmentType.PHYSICAL_EXAM
        elif any(kw in reason.lower() for kw in ["specialist", "complex", "detailed"]):
            suggestion = "Specialist Consultation (60 minutes)"
            state.appointment_type = AppointmentType.SPECIALIST_CONSULTATION
        else:
            suggestion = "General Consultation (30 minutes)"
            state.appointment_type = AppointmentType.GENERAL_CONSULTATION
        
        state.phase = ConversationPhase.COLLECTING_PREFERENCES
        
        context = (
            f"The user's reason for visit is: '{reason}'. "
            f"Recommend a {suggestion} appointment type. "
            f"Ask if this sounds appropriate or if they'd prefer something different. "
            f"Be conversational and empathetic. Keep response to 2-3 sentences."
        )
        
        return await self.chat_with_gemini(
            f"I need an appointment for: {reason}",
            state.session_id,
            context
        )
    
    async def _handle_slot_selection(
        self,
        entities: Dict,
        message: str,
        state: ConversationState
    ) -> str:
        """Handle when user selects a time slot or asks for available slots."""
        message_lower = message.lower()
        
        # Check if user is asking for available slots (not selecting one)
        availability_keywords = ["earliest", "available slots", "available", "slots", "what times", "when can"]
        if any(kw in message_lower for kw in availability_keywords):
            # User wants to see available slots
            if entities.get("date"):
                state.preferred_date = entities["date"]
            if entities.get("time_preference"):
                state.preferred_time_of_day = entities["time_preference"]
            return await self._show_available_slots(state)
        
        # Parse the selection
        if state.phase == ConversationPhase.SLOT_RECOMMENDATION:
            # Try to match the selection to available slots
            selected = self._parse_slot_selection(message, state)
            
            if selected:
                state.selected_slot = selected
                state.phase = ConversationPhase.COLLECTING_INFO
                
                # Format the selected time
                date_str = selected.get("date", "")
                time_str = selected.get("start_time", "")
                scheduling_url = selected.get("scheduling_url", "")
                
                # Store scheduling URL if available (for real Calendly)
                if scheduling_url:
                    state.scheduling_url = scheduling_url
                
                # Format date and time for display
                formatted_date = date_str or "the selected date"
                formatted_time = time_str or "the selected time"
                
                try:
                    if date_str:
                        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                        formatted_date = date_obj.strftime("%A, %B %d")
                    if time_str:
                        time_obj = datetime.strptime(time_str, "%H:%M")
                        formatted_time = time_obj.strftime("%I:%M %p").lstrip("0")
                except ValueError:
                    pass  # Keep the original strings if parsing fails
                
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
        
        # Get stored available slots from state
        available_slots = getattr(state, 'available_slots', [])
        
        # Default to tomorrow if no preferred date
        default_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        selected_date = state.preferred_date or default_date
        selected_time = None
        
        # Check for day names
        days_map = {
            "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
            "friday": 4, "saturday": 5, "sunday": 6,
            "tomorrow": None, "today": None
        }
        
        # Extract day
        for day_name in days_map.keys():
            if day_name in message_lower:
                if day_name == "today":
                    selected_date = datetime.now().strftime("%Y-%m-%d")
                elif day_name == "tomorrow":
                    selected_date = (datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + 
                                   timedelta(days=1)).strftime("%Y-%m-%d")
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
        
        # Try to find matching slot in available_slots (to get scheduling_url)
        if selected_time and available_slots:
            for slot in available_slots:
                if slot.get("start_time") == selected_time:
                    return {
                        "date": selected_date or state.preferred_date,
                        "start_time": selected_time,
                        "scheduling_url": slot.get("scheduling_url", "")
                    }
        
        if selected_date and selected_time:
            return {
                "date": selected_date,
                "start_time": selected_time,
                "scheduling_url": ""
            }
        elif selected_date:
            # If only date is selected, might need more info
            return {
                "date": selected_date,
                "start_time": selected_time,
                "scheduling_url": ""
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
        
        # All info collected - automatically book the appointment
        state.phase = ConversationPhase.CONFIRMATION
        
        slot = state.selected_slot or {}
        patient_info = state.patient_info or {}
        
        # Get scheduling URL if stored (for real Calendly)
        scheduling_url = getattr(state, 'scheduling_url', None) or slot.get('scheduling_url', '')
        
        # Book the appointment directly
        result = await self.booking_tool.book_appointment(
            appointment_type=state.appointment_type.value if state.appointment_type else "consultation",
            date=slot.get("date", ""),
            start_time=slot.get("start_time", ""),
            patient_name=patient_info.get("name", ""),
            patient_email=patient_info.get("email", ""),
            patient_phone=patient_info.get("phone", ""),
            reason=state.reason_for_visit or "General consultation",
            scheduling_url=scheduling_url
        )
        
        if result.get("success"):
            state.phase = ConversationPhase.COMPLETED
            
            # Format date/time for display
            date_str = slot.get("date", "")
            time_str = slot.get("start_time", "")
            
            try:
                date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                formatted_date = date_obj.strftime("%A, %B %d, %Y")
                time_obj = datetime.strptime(time_str, "%H:%M")
                formatted_time = time_obj.strftime("%I:%M %p").lstrip("0")
            except ValueError:
                formatted_date = date_str or "scheduled date"
                formatted_time = time_str or "scheduled time"
            
            appt_type = state.appointment_type.value if state.appointment_type else "consultation"
            duration = APPOINTMENT_DURATIONS.get(state.appointment_type, 30)
            confirmation_number = result.get("confirmation_number", "HCP" + str(uuid.uuid4())[:6].upper())
            
            # Check if this is a real Calendly booking (needs user action)
            if result.get("status") == "pending_user_action" and result.get("scheduling_url"):
                booking_url = result.get("scheduling_url")
                context = (
                    f"The appointment details have been prepared! To complete the booking and receive a confirmation email, "
                    f"the user needs to click this Calendly link: {booking_url}\n\n"
                    f"Details:\n"
                    f"- Date: {formatted_date}\n"
                    f"- Time: {formatted_time}\n"
                    f"- Duration: {duration} minutes\n"
                    f"- Name: {patient_info.get('name', 'N/A')}\n"
                    f"- Email: {patient_info.get('email', 'N/A')}\n\n"
                    f"Explain they need to click the link to finalize. Be warm and include the link."
                )
            else:
                context = (
                    f"🎉 APPOINTMENT CONFIRMED! Create a warm confirmation message with:\n"
                    f"- Confirmation #: {confirmation_number}\n"
                    f"- Date: {formatted_date}\n"
                    f"- Time: {formatted_time}\n"
                    f"- Duration: {duration} minutes\n"
                    f"- Patient: {patient_info.get('name', 'N/A')}\n"
                    f"- Phone: {patient_info.get('phone', 'N/A')}\n"
                    f"- Email: {patient_info.get('email', 'N/A')}\n"
                    f"- Reason: {state.reason_for_visit or 'General consultation'}\n\n"
                    f"Use emojis (📅✅) and remind about 24-hour cancellation policy. Be cheerful!"
                )
            
            return await self.chat_with_gemini(
                "booking confirmed",
                state.session_id,
                context
            )
        else:
            context = (
                f"There was an error booking: {result.get('error', 'Unknown error')}. "
                f"Apologize and offer to try again or call +1-555-123-4567."
            )
            return await self.chat_with_gemini("booking failed", state.session_id, context)

    async def _handle_confirmation(self, state: ConversationState) -> str:
        """Handle booking confirmation using Gemini."""
        
        # Handle confirmation based on current phase
        if state.phase == ConversationPhase.COLLECTING_PREFERENCES:
            # User confirmed appointment type, now show available slots
            last_user_msg = ""
            for msg in reversed(state.messages):
                if msg.role == "user":
                    last_user_msg = msg.content
                    break
            
            # Parse date from the message
            date = parse_date_reference(last_user_msg)
            time_pref = parse_time_preference(last_user_msg)
            
            if date:
                state.preferred_date = date
            if time_pref != "any":
                state.preferred_time_of_day = time_pref
            
            return await self._show_available_slots(state)
        
        elif state.phase == ConversationPhase.SLOT_RECOMMENDATION:
            # User is confirming a slot selection - move to collecting info
            # Check if there's a selected slot
            if state.selected_slot:
                state.phase = ConversationPhase.COLLECTING_INFO
                
                slot = state.selected_slot
                date_str = slot.get("date", "")
                time_str = slot.get("start_time", "")
                
                formatted_date = date_str or "the selected date"
                formatted_time = time_str or "the selected time"
                
                try:
                    if date_str:
                        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                        formatted_date = date_obj.strftime("%A, %B %d")
                    if time_str:
                        time_obj = datetime.strptime(time_str, "%H:%M")
                        formatted_time = time_obj.strftime("%I:%M %p").lstrip("0")
                except ValueError:
                    pass
                
                context = (
                    f"The user has confirmed they want to book an appointment on {formatted_date} at {formatted_time}. "
                    f"Now ask for their full name, phone number, and email address to complete the booking. "
                    f"Be friendly and professional."
                )
                
                return await self.chat_with_gemini("confirm slot", state.session_id, context)
            else:
                # No slot selected yet, ask them to select
                context = (
                    "The user wants to confirm but hasn't selected a specific time slot yet. "
                    "Ask them which of the available times works best for them."
                )
                return await self.chat_with_gemini("confirm", state.session_id, context)
        
        elif state.phase == ConversationPhase.COLLECTING_INFO:
            # User is confirming while we're collecting info - check what we have
            if state.patient_info and all([
                state.patient_info.get("name"),
                state.patient_info.get("phone"),
                state.patient_info.get("email")
            ]):
                # All info collected, move to final confirmation
                state.phase = ConversationPhase.CONFIRMATION
                return await self._handle_confirmation(state)
            else:
                # Still need info
                missing = []
                if not state.patient_info or not state.patient_info.get("name"):
                    missing.append("full name")
                if not state.patient_info or not state.patient_info.get("phone"):
                    missing.append("phone number")
                if not state.patient_info or not state.patient_info.get("email"):
                    missing.append("email address")
                
                context = (
                    f"The user said yes but we still need their {', '.join(missing)} to complete the booking. "
                    f"Kindly ask them to provide this information."
                )
                return await self.chat_with_gemini("need info", state.session_id, context)
        
        elif state.phase != ConversationPhase.CONFIRMATION:
            # Unknown phase, ask what they want to confirm
            context = "The user said something affirmative. Ask what they'd like to confirm or help with."
            return await self.chat_with_gemini("yes", state.session_id, context)
        
        # Book the appointment
        slot = state.selected_slot or {}
        patient_info = state.patient_info or {}
        
        # Get scheduling URL if stored (for real Calendly)
        scheduling_url = getattr(state, 'scheduling_url', None) or slot.get('scheduling_url', '')
        
        result = await self.booking_tool.book_appointment(
            appointment_type=state.appointment_type.value if state.appointment_type else "consultation",
            date=slot.get("date", ""),
            start_time=slot.get("start_time", ""),
            patient_name=patient_info.get("name", ""),
            patient_email=patient_info.get("email", ""),
            patient_phone=patient_info.get("phone", ""),
            reason=state.reason_for_visit or "General consultation",
            scheduling_url=scheduling_url
        )
        
        if result.get("success"):
            state.phase = ConversationPhase.COMPLETED
            
            # Check if this is a real Calendly booking (needs user action)
            if result.get("status") == "pending_user_action" and result.get("scheduling_url"):
                # Real Calendly - provide the booking link
                booking_url = result.get("scheduling_url")
                context = (
                    f"The appointment details have been prepared! However, to complete the booking "
                    f"and receive a confirmation email, the user needs to click this Calendly link:\n\n"
                    f"🔗 {booking_url}\n\n"
                    f"Details prepared:\n"
                    f"- Date: {slot.get('date', 'N/A')}\n"
                    f"- Time: {slot.get('start_time', 'N/A')}\n"
                    f"- Name: {patient_info.get('name', 'N/A')}\n"
                    f"- Email: {patient_info.get('email', 'N/A')}\n\n"
                    f"Explain that they need to click the link to finalize the booking. "
                    f"Calendly will send them a confirmation email with all the details. "
                    f"Be warm and helpful. Make sure to include the actual booking link in your response."
                )
            else:
                # Mock Calendly - booking is complete
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
        
        # Use preferred date or default to tomorrow (Calendly requires future dates)
        if state.preferred_date:
            date = state.preferred_date
        else:
            tomorrow = datetime.now() + timedelta(days=1)
            date = tomorrow.strftime("%Y-%m-%d")
            # Store the date so slot selection knows which date we showed
            state.preferred_date = date
        
        appt_type = state.appointment_type.value if state.appointment_type else "consultation"
        
        # Get availability from Calendly API (mock or real)
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
        
        # Store available slots in state for later reference (includes scheduling_url)
        state.available_slots = display_slots
        
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
