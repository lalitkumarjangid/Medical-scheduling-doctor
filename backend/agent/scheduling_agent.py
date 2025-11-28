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
        
        # Check for date/time preference before checking confirm intent
        # This ensures "Tomorrow morning would be great" is treated as date selection
        date = parse_date_reference(message)
        time_pref = parse_time_preference(message)
        if date or time_pref != "any":
            entities["date"] = date
            entities["time_preference"] = time_pref
            if current_phase in [ConversationPhase.UNDERSTANDING_NEEDS.value, 
                                 ConversationPhase.COLLECTING_PREFERENCES.value,
                                 ConversationPhase.SLOT_RECOMMENDATION.value]:
                return Intent.PROVIDE_INFO, entities
        
        # Confirm intent - only match when not providing date/time info
        confirm_words = ["yes", "confirm", "book it", "sounds good", "perfect", "let's do it", "that works"]
        if any(cw in message_lower for cw in confirm_words) and not date:
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
            
            # Use async wrapper for Gemini with safety settings
            response = await asyncio.to_thread(
                lambda: model.generate_content(
                    gemini_messages,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.7,
                        max_output_tokens=500
                    ),
                    safety_settings={
                        'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE',
                        'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE',
                        'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE',
                        'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE',
                    }
                )
            )
            
            # Check if response has valid text
            if response.candidates and len(response.candidates) > 0:
                candidate = response.candidates[0]
                if candidate.content and candidate.content.parts:
                    return candidate.content.parts[0].text
            
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
            
            # Generate response with safety settings
            response = await asyncio.to_thread(
                lambda: chat.send_message(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.7,
                        max_output_tokens=500
                    ),
                    safety_settings={
                        'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE',
                        'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE',
                        'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE',
                        'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE',
                    }
                )
            )
            
            # Check if response has valid text
            if response.candidates and len(response.candidates) > 0:
                candidate = response.candidates[0]
                if candidate.content and candidate.content.parts:
                    return candidate.content.parts[0].text
                elif candidate.finish_reason:
                    print(f"Gemini finish_reason: {candidate.finish_reason}")
                    return self._generate_contextual_fallback(message, context)
            
            return response.text
        except Exception as e:
            print(f"Gemini chat error: {e}")
            return self._generate_fallback_response([{"role": "user", "content": message}])
    
    def _generate_fallback_response(self, messages: List[Dict]) -> str:
        """Generate a fallback response when LLM is unavailable."""
        return "I'd be happy to help you schedule an appointment or answer questions about our clinic. What can I help you with today?"
    
    def _generate_contextual_fallback(self, message: str, context: Optional[str] = None) -> str:
        """Generate a contextual fallback response based on the conversation context."""
        message_lower = message.lower()
        
        # Check for scheduling-related messages
        if any(word in message_lower for word in ["schedule", "book", "appointment", "see doctor"]):
            if context and "Available" in context:
                return "I can help you schedule an appointment! Here are our available time slots. Please let me know which date and time works best for you, and I'll also need to know the reason for your visit."
            return "I'd be happy to help you schedule an appointment! Could you tell me what brings you in today, and when you'd prefer to come in?"
        
        # Check for greeting
        if any(word in message_lower for word in ["hi", "hello", "hey", "good morning", "good afternoon"]):
            return "Hello! Welcome to HealthCare Plus Clinic. I can help you schedule an appointment or answer questions about our services. How can I assist you today?"
        
        # Check for time/date related
        if any(word in message_lower for word in ["morning", "afternoon", "tomorrow", "today", "monday", "tuesday", "wednesday", "thursday", "friday"]):
            return "Let me check our availability for that time. Could you also tell me the reason for your visit so I can book the right type of appointment for you?"
        
        # Default
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
            # Get available slots for the next few days to show to user
            available_slots_info = await self._get_upcoming_available_slots()
            context_parts.append(
                "The user wants to schedule an appointment. "
                "Ask about the reason for their visit AND immediately show them the available slots below. "
                "You MUST include the available slots in your response."
            )
            context_parts.append(f"\n=== AVAILABLE APPOINTMENT SLOTS (INCLUDE THESE IN YOUR RESPONSE) ===\n{available_slots_info}\n===")
            context_parts.append(
                "IMPORTANT: Show ALL these available slots to the user with dates and times formatted nicely. "
                "Ask what brings them in and which slot works for them."
            )
            if entities.get("date"):
                context_parts.append(f"User mentioned date preference: {entities['date']}")
            if entities.get("time_preference"):
                context_parts.append(f"User mentioned time preference: {entities['time_preference']}")
        
        elif intent == Intent.PROVIDE_INFO:
            # User is providing information during booking
            if state.phase == ConversationPhase.UNDERSTANDING_NEEDS:
                # Check if date/time preference was provided along with reason
                if entities.get("date") or entities.get("time_preference"):
                    # Reason already understood, now get availability
                    date = entities.get("date") or datetime.now().strftime("%Y-%m-%d")
                    result = await self.availability_tool.get_available_slots(
                        date,
                        state.appointment_type.value if state.appointment_type else "consultation"
                    )
                    
                    if result.get("success"):
                        slots = result.get("available_slots", [])
                        time_pref = entities.get("time_preference", "any")
                        
                        # Filter by time preference
                        if time_pref == "morning":
                            slots = [s for s in slots if int(s["start_time"].split(":")[0]) < 12]
                        elif time_pref == "afternoon":
                            slots = [s for s in slots if int(s["start_time"].split(":")[0]) >= 12]
                        
                        slots = slots[:5]  # Limit to 5 slots
                        
                        if slots:
                            slots_text = ", ".join([s["start_time"] for s in slots])
                            context_parts.append(
                                f"Available slots for {date}: {slots_text}\n"
                                "Present these options in a friendly, readable format and ask which time works best for them."
                            )
                        else:
                            # Get alternative dates
                            alt_result = await self.availability_tool.get_available_dates(14, 
                                state.appointment_type.value if state.appointment_type else "consultation")
                            alt_dates = alt_result.get("available_dates", [])[:3]
                            if alt_dates:
                                alt_text = ", ".join([f"{d['day_name']} {d['date']}" for d in alt_dates])
                                context_parts.append(
                                    f"No available slots match the requested time. Alternative dates with availability: {alt_text}. "
                                    "Offer these alternatives to the user."
                                )
                            else:
                                context_parts.append("No slots available in the coming days. Suggest calling the office.")
                else:
                    context_parts.append(
                        f"User provided reason for visit: '{message}'. "
                        "Acknowledge this and recommend an appropriate appointment type, then ask for date/time preference."
                    )
            elif state.phase == ConversationPhase.COLLECTING_PREFERENCES:
                # User providing date/time preference
                date = entities.get("date") or parse_date_reference(message)
                time_pref = entities.get("time_preference") or parse_time_preference(message)
                
                if date or time_pref != "any":
                    # Fetch availability from mock Calendly
                    result = await self.availability_tool.get_available_slots(
                        date or datetime.now().strftime("%Y-%m-%d"),
                        state.appointment_type.value if state.appointment_type else "consultation"
                    )
                    
                    if result.get("success"):
                        slots = result.get("available_slots", [])
                        
                        # Filter by time preference
                        if time_pref == "morning":
                            slots = [s for s in slots if int(s["start_time"].split(":")[0]) < 12]
                        elif time_pref == "afternoon":
                            slots = [s for s in slots if int(s["start_time"].split(":")[0]) >= 12]
                        
                        slots = slots[:5]
                        
                        if slots:
                            slots_text = ", ".join([s["start_time"] for s in slots])
                            context_parts.append(
                                f"Available {time_pref} slots for {date or 'today'}: {slots_text}\n"
                                "Present these options clearly and ask which time works best for the user."
                            )
                        else:
                            # Get alternative dates
                            alt_result = await self.availability_tool.get_available_dates(14, 
                                state.appointment_type.value if state.appointment_type else "consultation")
                            alt_dates = alt_result.get("available_dates", [])[:3]
                            if alt_dates:
                                alt_text = ", ".join([f"{d['day_name']} {d['date']}" for d in alt_dates])
                                context_parts.append(
                                    f"No slots available for the requested time. Alternative dates: {alt_text}. "
                                    "Offer these alternatives."
                                )
                else:
                    context_parts.append("Ask about their preferred date and time (morning/afternoon).")
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
                # Check if date/time was provided
                if entities.get("date") or entities.get("time_preference"):
                    # Date/time provided - transition to slot recommendation
                    if entities.get("date"):
                        state.preferred_date = entities["date"]
                    if entities.get("time_preference"):
                        state.preferred_time_of_day = entities["time_preference"]
                    state.phase = ConversationPhase.SLOT_RECOMMENDATION
                else:
                    # Reason for visit provided
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
            
            elif state.phase == ConversationPhase.COLLECTING_PREFERENCES:
                # Date/time preference provided
                if entities.get("date"):
                    state.preferred_date = entities["date"]
                if entities.get("time_preference"):
                    state.preferred_time_of_day = entities["time_preference"]
                if entities.get("date") or entities.get("time_preference"):
                    state.phase = ConversationPhase.SLOT_RECOMMENDATION
            
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
    
    async def _get_upcoming_available_slots(self, days: int = 5, appointment_type: str = "consultation") -> str:
        """
        Get available slots for the next few days from ALL doctors.
        
        Args:
            days: Number of days to check
            appointment_type: Type of appointment
            
        Returns:
            Formatted string with available slots including doctor names
        """
        from datetime import timedelta
        import aiohttp
        
        slots_info = []
        current_date = datetime.now()
        
        for i in range(days):
            check_date = current_date + timedelta(days=i)
            date_str = check_date.strftime("%Y-%m-%d")
            day_name = check_date.strftime("%A, %B %d")
            
            # Try to get all doctors availability from the API
            try:
                async with aiohttp.ClientSession() as session:
                    url = f"{self.api_base_url}/api/calendly/availability/all-doctors?date={date_str}&appointment_type={appointment_type}"
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            doctors_with_slots = data.get("doctors_with_availability", [])
                            
                            if doctors_with_slots:
                                day_info = f"\n📅 **{day_name}**"
                                
                                for doctor_data in doctors_with_slots:
                                    doctor_name = doctor_data.get("doctor_name", "Unknown")
                                    specialty = doctor_data.get("specialty", "")
                                    slots = doctor_data.get("slots", [])
                                    
                                    if slots:
                                        # Format times nicely
                                        morning_slots = []
                                        afternoon_slots = []
                                        
                                        for slot in slots[:6]:  # Limit slots per doctor
                                            time_str = slot["start_time"]
                                            hour = int(time_str.split(":")[0])
                                            
                                            # Convert to 12-hour format
                                            if hour < 12:
                                                h12 = hour if hour > 0 else 12
                                                formatted_time = f"{h12}:{time_str.split(':')[1]} AM"
                                                morning_slots.append(formatted_time)
                                            else:
                                                h12 = hour - 12 if hour > 12 else hour
                                                formatted_time = f"{h12}:{time_str.split(':')[1]} PM"
                                                afternoon_slots.append(formatted_time)
                                        
                                        day_info += f"\n   👨‍⚕️ **{doctor_name}** ({specialty})"
                                        if morning_slots:
                                            day_info += f"\n      Morning: {', '.join(morning_slots[:3])}"
                                        if afternoon_slots:
                                            day_info += f"\n      Afternoon: {', '.join(afternoon_slots[:3])}"
                                
                                slots_info.append(day_info)
                            continue
            except Exception as e:
                print(f"Error fetching all doctors availability: {e}")
            
            # Fallback to single doctor availability
            result = await self.availability_tool.get_available_slots(date_str, appointment_type)
            
            if result.get("success"):
                available = result.get("available_slots", [])
                if available:
                    # Format times nicely
                    morning_slots = []
                    afternoon_slots = []
                    
                    for slot in available:
                        time_str = slot["start_time"]
                        hour = int(time_str.split(":")[0])
                        
                        # Convert to 12-hour format
                        if hour < 12:
                            h12 = hour if hour > 0 else 12
                            formatted_time = f"{h12}:{time_str.split(':')[1]} AM"
                            morning_slots.append(formatted_time)
                        else:
                            h12 = hour - 12 if hour > 12 else hour
                            formatted_time = f"{h12}:{time_str.split(':')[1]} PM"
                            afternoon_slots.append(formatted_time)
                    
                    day_info = f"\n📅 **{day_name}**"
                    if morning_slots:
                        day_info += f"\n   Morning: {', '.join(morning_slots[:4])}"
                    if afternoon_slots:
                        day_info += f"\n   Afternoon: {', '.join(afternoon_slots[:4])}"
                    
                    slots_info.append(day_info)
        
        if slots_info:
            return "\n".join(slots_info)
        else:
            return "No available slots in the next few days. Please call the office at +1-555-123-4567."
    
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

