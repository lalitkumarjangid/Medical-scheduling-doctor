#!/bin/bash
# Run the Medical Appointment Scheduling Agent backend

cd "$(dirname "$0")"
source venv/bin/activate
python main.py "$@"
