# Medical Appointment Scheduling Agent

An intelligent conversational agent that helps patients schedule medical appointments through a natural chat interface. Built with FastAPI, React, and OpenAI GPT-4.

![Architecture](architecture_diagram.png)

## 🌟 Features

### Core Capabilities
- **🗓️ Appointment Scheduling**: Book, reschedule, and cancel appointments
- **💬 Natural Conversation**: Context-aware dialogue with empathetic responses
- **❓ FAQ Answering**: RAG-powered answers to clinic questions
- **⏰ Smart Slot Recommendations**: Time preferences and intelligent suggestions
- **🔄 Context Switching**: Seamlessly handle FAQs during booking flow

### Appointment Types
| Type | Duration |
|------|----------|
| General Consultation | 30 minutes |
| Follow-up Visit | 15 minutes |
| Physical Exam | 45 minutes |
| Specialist Consultation | 60 minutes |

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Frontend (React)                         │
│  ┌─────────────┐  ┌──────────────────┐  ┌───────────────────┐   │
│  │ ChatInterface│  │AppointmentConfirm│  │   Quick Actions   │   │
│  └──────┬──────┘  └────────┬─────────┘  └─────────┬─────────┘   │
└─────────┼──────────────────┼───────────────────────┼─────────────┘
          │                  │                       │
          └──────────────────┼───────────────────────┘
                             │ REST API
┌────────────────────────────┼────────────────────────────────────┐
│                    FastAPI Backend                               │
│  ┌─────────────────────────┼─────────────────────────────────┐  │
│  │              Chat API (/api/chat)                          │  │
│  └─────────────────────────┼─────────────────────────────────┘  │
│                            │                                     │
│  ┌─────────────────────────▼─────────────────────────────────┐  │
│  │              Scheduling Agent                              │  │
│  │  ┌────────────┐ ┌──────────────┐ ┌───────────────────┐    │  │
│  │  │Intent Class│ │Conversation  │ │ Response Generator│    │  │
│  │  │  ifier     │ │   Manager    │ │   (LLM/Rules)     │    │  │
│  │  └─────┬──────┘ └──────┬───────┘ └────────┬──────────┘    │  │
│  └────────┼───────────────┼──────────────────┼───────────────┘  │
│           │               │                  │                   │
│  ┌────────▼───────┐ ┌─────▼──────┐ ┌────────▼─────────┐         │
│  │ Availability   │ │ Booking    │ │   FAQ RAG        │         │
│  │   Tool         │ │  Tool      │ │   System         │         │
│  └────────┬───────┘ └─────┬──────┘ └────────┬─────────┘         │
│           │               │                  │                   │
│  ┌────────▼───────────────▼──────┐ ┌────────▼─────────┐         │
│  │    Mock Calendly API          │ │  ChromaDB Vector │         │
│  │  /api/calendly/*              │ │     Store        │         │
│  └───────────────────────────────┘ └──────────────────┘         │
└─────────────────────────────────────────────────────────────────┘
```

## 🛠️ Tech Stack

| Component | Technology |
|-----------|------------|
| **Backend** | FastAPI (Python 3.10+) |
| **LLM** | OpenAI GPT-4 Turbo |
| **Vector Database** | ChromaDB |
| **Frontend** | React 18 + Vite + TailwindCSS |
| **Calendar API** | Mock Calendly Implementation |

## 📁 Project Structure

```
appointment-scheduling-agent/
├── README.md
├── .env.example
├── requirements.txt
├── architecture_diagram.png
├── backend/
│   ├── main.py                    # FastAPI application entry
│   ├── agent/
│   │   ├── scheduling_agent.py    # Core conversation agent
│   │   └── prompts.py             # LLM prompts
│   ├── rag/
│   │   ├── faq_rag.py             # FAQ retrieval system
│   │   ├── embeddings.py          # Embedding utilities
│   │   └── vector_store.py        # ChromaDB integration
│   ├── api/
│   │   ├── chat.py                # Chat API endpoints
│   │   └── calendly_integration.py # Mock Calendly API
│   ├── tools/
│   │   ├── availability_tool.py   # Slot checking
│   │   └── booking_tool.py        # Appointment booking
│   └── models/
│       └── schemas.py             # Pydantic models
├── frontend/
│   ├── package.json
│   ├── src/
│   │   ├── App.jsx
│   │   └── components/
│   │       ├── ChatInterface.jsx
│   │       └── AppointmentConfirmation.jsx
├── data/
│   ├── clinic_info.json           # FAQ and clinic data
│   └── doctor_schedule.json       # Schedule configuration
└── tests/
    └── test_agent.py              # Unit tests
```

## 🚀 Setup Instructions

### Prerequisites
- Python 3.10+
- Node.js 18+
- OpenAI API key

### 1. Clone and Setup Environment

```bash
cd appointment-scheduling-agent

# Create Python virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install backend dependencies
pip install -r requirements.txt
```

### 2. Configure Environment Variables

```bash
# Copy example env file
cp .env.example .env

# Edit .env and add your OpenAI API key
# OPENAI_API_KEY=your_key_here
```

### 3. Start Backend Server

```bash
cd backend
python main.py

# Or with uvicorn directly
uvicorn main:app --reload --port 8000
```

Backend will be available at: `http://localhost:8000`
- API docs: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`

### 4. Setup Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend will be available at: `http://localhost:3000`

## 🧠 System Design

### Agent Conversation Flow

```
┌─────────────┐
│   START     │
└──────┬──────┘
       │
       ▼
┌─────────────┐    ┌─────────────┐
│  GREETING   │───▶│  Classify   │
└─────────────┘    │   Intent    │
                   └──────┬──────┘
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
        ▼                 ▼                 ▼
┌───────────────┐ ┌───────────────┐ ┌───────────────┐
│   SCHEDULE    │ │      FAQ      │ │   CANCEL/     │
│               │ │               │ │  RESCHEDULE   │
└───────┬───────┘ └───────┬───────┘ └───────────────┘
        │                 │
        ▼                 │
┌───────────────┐         │
│ UNDERSTANDING │         │
│    NEEDS      │◀────────┘ (return after FAQ)
└───────┬───────┘
        │
        ▼
┌───────────────┐
│  COLLECTING   │
│  PREFERENCES  │
└───────┬───────┘
        │
        ▼
┌───────────────┐
│     SLOT      │
│RECOMMENDATION │
└───────┬───────┘
        │
        ▼
┌───────────────┐
│  COLLECTING   │
│    INFO       │
└───────┬───────┘
        │
        ▼
┌───────────────┐
│ CONFIRMATION  │
└───────┬───────┘
        │
        ▼
┌───────────────┐
│   COMPLETED   │
└───────────────┘
```

### Calendly Integration (Mock API)

The mock Calendly API provides:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/calendly/availability` | GET | Get available slots for a date |
| `/api/calendly/book` | POST | Book an appointment |
| `/api/calendly/cancel` | POST | Cancel an appointment |
| `/api/calendly/reschedule` | POST | Reschedule an appointment |
| `/api/calendly/schedule/dates` | GET | Get dates with availability |

### RAG Pipeline for FAQs

1. **Indexing**: Clinic info and FAQs are embedded using ChromaDB's default embedder
2. **Retrieval**: User questions are matched against the vector store
3. **Generation**: Relevant context is used to generate natural responses
4. **Context Switch**: Agent tracks conversation state to return to scheduling after FAQ

### Tool Calling Strategy

```python
# Intent → Tool Mapping
SCHEDULE → AvailabilityTool.get_available_slots()
         → BookingTool.book_appointment()
FAQ      → FAQRAG.get_answer()
CANCEL   → BookingTool.cancel_appointment()
```

## 📊 Scheduling Logic

### How Available Slots Are Determined

1. Load doctor's working hours for the requested day
2. Generate all possible slots based on appointment duration
3. Filter out:
   - Lunch break periods
   - Already booked appointments
   - Past times (for today)
   - Blocked dates (holidays, vacations)
4. Return available slots matching user's time preference

### Conflict Prevention

- Slots are locked during booking transaction
- Double-booking is prevented at the API level
- Real-time availability check before confirmation

## 🧪 Testing

### Run Tests

```bash
cd tests
pytest test_agent.py -v
```

### Example Conversations

#### Successful Booking Flow
```
User: I need to see the doctor
Agent: I'd be happy to help you schedule an appointment! What's the main reason for your visit today?

User: I've been having headaches
Agent: I understand. For that, I'd recommend a General Consultation (30 minutes) where the doctor can properly assess your concerns. Does that sound appropriate?

User: Yes, that's fine
Agent: Great! When would you like to come in? Do you have a preference for morning or afternoon appointments?

User: Tomorrow afternoon
Agent: Let me check our afternoon availability for tomorrow. I have these options:
• 1:00 PM
• 2:30 PM
• 3:30 PM
Which time works best for you?

User: 2:30 PM
Agent: Excellent! Before I confirm, I'll need your full name?

User: John Smith
Agent: Thanks! And what's your phone number?

User: 555-123-4567
Agent: And your email address?

User: john@example.com
Agent: Perfect! Let me confirm the details:
📅 Date: Tomorrow
🕐 Time: 2:30 PM
⏱️ Duration: 30 minutes
👤 Name: John Smith
📞 Phone: 555-123-4567
📧 Email: john@example.com

Shall I confirm this appointment?

User: Yes
Agent: 🎉 Your appointment is confirmed!
[Full confirmation details...]
```

#### FAQ During Booking
```
User: I want to book an appointment
Agent: I'd be happy to help! What brings you in today?

User: Actually, first - what insurance do you accept?
Agent: Great question! We accept most major insurance providers including Blue Cross Blue Shield, Aetna, Cigna, UnitedHealthcare, and Medicare. We also accept self-pay patients.

Would you like to continue with scheduling your appointment?

User: Yes, I have a cold
Agent: I understand. For cold symptoms, a General Consultation (30 minutes) would be appropriate. When would you like to come in?
```

### Edge Cases Covered

- ✅ No available slots → Offer alternatives
- ✅ Past dates → Redirect to future dates
- ✅ Outside business hours → Suggest valid times
- ✅ Ambiguous time ("around 3") → Request clarification
- ✅ User changes mind → Allow restart
- ✅ API failures → Graceful error messages

## 📝 API Documentation

### Chat Endpoint

```bash
POST /api/chat/message

Request:
{
  "message": "I want to book an appointment",
  "session_id": "optional-session-id"
}

Response:
{
  "message": "I'd be happy to help you schedule an appointment!...",
  "session_id": "uuid-v4",
  "intent": "SCHEDULE",
  "phase": "understanding_needs",
  "booking_status": null
}
```

### Availability Endpoint

```bash
GET /api/calendly/availability?date=2025-12-01&appointment_type=consultation

Response:
{
  "date": "2025-12-01",
  "appointment_type": "consultation",
  "duration_minutes": 30,
  "available_slots": [
    {"start_time": "09:00", "end_time": "09:30", "available": true},
    {"start_time": "10:00", "end_time": "10:30", "available": true}
  ]
}
```

## 🔧 Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key | Required |
| `LLM_MODEL` | Model to use | gpt-4-turbo |
| `BACKEND_PORT` | Backend port | 8000 |
| `FRONTEND_PORT` | Frontend port | 3000 |
| `VECTOR_DB_PATH` | ChromaDB path | ./data/vectordb |
| `TIMEZONE` | Clinic timezone | America/New_York |

## 📄 License

MIT License - See LICENSE file for details.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Open a Pull Request
# Medical-scheduling-doctor
