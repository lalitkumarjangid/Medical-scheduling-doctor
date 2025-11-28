"""
Chat API endpoint for the Medical Appointment Scheduling Agent.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict
import asyncio

from models.schemas import ChatRequest, ChatResponse
from agent.scheduling_agent import SchedulingAgent

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Initialize agent (singleton pattern)
_agent: Optional[SchedulingAgent] = None


def get_agent() -> SchedulingAgent:
    """Get or create the scheduling agent instance."""
    global _agent
    if _agent is None:
        _agent = SchedulingAgent()
    return _agent


class MessageRequest(BaseModel):
    """Request model for sending a message."""
    message: str
    session_id: Optional[str] = None


class MessageResponse(BaseModel):
    """Response model for chat messages."""
    message: str
    session_id: str
    intent: Optional[str] = None
    phase: Optional[str] = None
    booking_status: Optional[Dict] = None


class ConversationHistoryResponse(BaseModel):
    """Response model for conversation history."""
    session_id: str
    messages: List[Dict]
    current_phase: str


@router.post("/message", response_model=MessageResponse)
async def send_message(request: MessageRequest):
    """
    Send a message to the scheduling agent and get a response.
    
    - **message**: The user's message
    - **session_id**: Optional session ID for conversation continuity
    """
    agent = get_agent()
    
    try:
        result = await agent.process_message(
            message=request.message,
            session_id=request.session_id
        )
        
        return MessageResponse(
            message=result["message"],
            session_id=result["session_id"],
            intent=result.get("intent"),
            phase=result.get("phase"),
            booking_status=result.get("booking_status")
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error processing message: {str(e)}"
        )


@router.get("/session/{session_id}", response_model=ConversationHistoryResponse)
async def get_session(session_id: str):
    """
    Get the conversation history for a session.
    
    - **session_id**: The session ID to retrieve
    """
    agent = get_agent()
    
    if session_id not in agent.sessions:
        raise HTTPException(
            status_code=404,
            detail="Session not found"
        )
    
    state = agent.sessions[session_id]
    
    return ConversationHistoryResponse(
        session_id=session_id,
        messages=[
            {
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat() if msg.timestamp else None
            }
            for msg in state.messages
        ],
        current_phase=state.phase.value
    )


@router.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """
    Delete a conversation session.
    
    - **session_id**: The session ID to delete
    """
    agent = get_agent()
    
    if session_id in agent.sessions:
        del agent.sessions[session_id]
        return {"status": "deleted", "session_id": session_id}
    
    raise HTTPException(
        status_code=404,
        detail="Session not found"
    )


@router.post("/reset")
async def reset_all_sessions():
    """
    Reset all conversation sessions.
    Use with caution - this clears all active sessions.
    """
    agent = get_agent()
    agent.sessions.clear()
    return {"status": "all sessions cleared"}


# Health check endpoint
@router.get("/health")
async def health_check():
    """Check if the chat service is healthy."""
    return {
        "status": "healthy",
        "service": "chat-api",
        "agent_initialized": _agent is not None
    }
