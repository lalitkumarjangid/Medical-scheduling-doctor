"""
Medical Appointment Scheduling Agent - FastAPI Backend

This is the main entry point for the backend application.
It provides APIs for:
- Chat interface with the scheduling agent
- Calendar/availability management (Mock Calendly integration)
- FAQ retrieval using RAG
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    # Try .env.example for default values
    env_example = Path(__file__).parent.parent / ".env.example"
    if env_example.exists():
        load_dotenv(env_example)

# Import routers
from api.calendly_integration import router as calendly_router
from api.chat import router as chat_router
from rag.faq_rag import get_faq_rag


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    Initializes resources on startup and cleans up on shutdown.
    """
    # Startup
    print("🏥 Starting Medical Appointment Scheduling Agent...")
    
    # Initialize the FAQ RAG system (pre-load vector store)
    try:
        persist_dir = os.getenv("VECTOR_DB_PATH", "./data/vectordb")
        faq_rag = get_faq_rag(persist_dir)
        print(f"✅ FAQ RAG system initialized with {faq_rag.vector_store.count()} documents")
    except Exception as e:
        print(f"⚠️ Warning: Could not initialize FAQ RAG: {e}")
    
    print("✅ Backend ready!")
    
    yield
    
    # Shutdown
    print("👋 Shutting down...")


# Create FastAPI application
app = FastAPI(
    title="Medical Appointment Scheduling Agent",
    description="""
    An intelligent conversational agent for scheduling medical appointments.
    
    ## Features
    - 🗓️ **Schedule Appointments**: Book appointments with available time slots
    - 💬 **Natural Conversation**: Chat interface with context awareness
    - ❓ **FAQ Answers**: RAG-powered answers to clinic questions
    - 🔄 **Reschedule/Cancel**: Manage existing appointments
    
    ## API Endpoints
    - `/api/chat/message`: Send messages to the scheduling agent
    - `/api/calendly/availability`: Check available time slots
    - `/api/calendly/book`: Book an appointment
    """,
    version="1.0.0",
    lifespan=lifespan,
)

# Configure CORS
frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        frontend_url,
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",  # Vite default
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(calendly_router)
app.include_router(chat_router)


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Medical Appointment Scheduling Agent",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "endpoints": {
            "chat": "/api/chat/message",
            "availability": "/api/calendly/availability",
            "book": "/api/calendly/book"
        }
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "medical-scheduling-agent",
        "components": {
            "api": "up",
            "database": "up"  # Vector store
        }
    }


if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("BACKEND_PORT", 8000))
    debug = os.getenv("DEBUG", "false").lower() == "true"
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=debug
    )
