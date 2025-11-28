import { useState } from 'react'
import ChatInterface from './components/ChatInterface'
import AppointmentConfirmation from './components/AppointmentConfirmation'

function App() {
  const [confirmedAppointment, setConfirmedAppointment] = useState(null)

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-white to-green-50">
      {/* Header */}
      <header className="bg-white shadow-sm border-b border-gray-100">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-3">
              <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-green-500 rounded-lg flex items-center justify-center">
                <svg 
                  className="w-6 h-6 text-white" 
                  fill="none" 
                  stroke="currentColor" 
                  viewBox="0 0 24 24"
                >
                  <path 
                    strokeLinecap="round" 
                    strokeLinejoin="round" 
                    strokeWidth={2} 
                    d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" 
                  />
                </svg>
              </div>
              <div>
                <h1 className="text-xl font-bold text-gray-900">HealthCare Plus</h1>
                <p className="text-sm text-gray-500">Appointment Scheduling</p>
              </div>
            </div>
            <div className="flex items-center space-x-4">
              <a 
                href="tel:+1-555-123-4567"
                className="hidden sm:flex items-center text-gray-600 hover:text-blue-600 transition-colors"
              >
                <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z" />
                </svg>
                +1-555-123-4567
              </a>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Chat Interface - Main */}
          <div className="lg:col-span-2">
            <ChatInterface onAppointmentConfirmed={setConfirmedAppointment} />
          </div>

          {/* Sidebar */}
          <div className="space-y-6">
            {/* Confirmed Appointment */}
            {confirmedAppointment && (
              <AppointmentConfirmation appointment={confirmedAppointment} />
            )}

            {/* Quick Info Card */}
            <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
              <h3 className="font-semibold text-gray-900 mb-4 flex items-center">
                <svg className="w-5 h-5 mr-2 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                Quick Information
              </h3>
              <div className="space-y-4 text-sm">
                <div>
                  <p className="font-medium text-gray-700">Hours of Operation</p>
                  <p className="text-gray-500">Mon-Thu: 8AM - 6PM</p>
                  <p className="text-gray-500">Fri: 8AM - 5PM</p>
                  <p className="text-gray-500">Sat: 9AM - 1PM</p>
                  <p className="text-gray-500">Sun: Closed</p>
                </div>
                <div>
                  <p className="font-medium text-gray-700">Location</p>
                  <p className="text-gray-500">123 Medical Center Drive</p>
                  <p className="text-gray-500">Suite 200, Springfield, IL</p>
                </div>
                <div>
                  <p className="font-medium text-gray-700">Contact</p>
                  <p className="text-gray-500">+1-555-123-4567</p>
                  <p className="text-gray-500">appointments@healthcareplus.com</p>
                </div>
              </div>
            </div>

            {/* Appointment Types */}
            <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
              <h3 className="font-semibold text-gray-900 mb-4 flex items-center">
                <svg className="w-5 h-5 mr-2 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
                </svg>
                Appointment Types
              </h3>
              <div className="space-y-3">
                <div className="flex justify-between items-center p-2 rounded-lg bg-gray-50">
                  <span className="text-gray-700">General Consultation</span>
                  <span className="text-sm text-gray-500">30 min</span>
                </div>
                <div className="flex justify-between items-center p-2 rounded-lg bg-gray-50">
                  <span className="text-gray-700">Follow-up Visit</span>
                  <span className="text-sm text-gray-500">15 min</span>
                </div>
                <div className="flex justify-between items-center p-2 rounded-lg bg-gray-50">
                  <span className="text-gray-700">Physical Exam</span>
                  <span className="text-sm text-gray-500">45 min</span>
                </div>
                <div className="flex justify-between items-center p-2 rounded-lg bg-gray-50">
                  <span className="text-gray-700">Specialist Consultation</span>
                  <span className="text-sm text-gray-500">60 min</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="bg-white border-t border-gray-100 mt-8">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <p className="text-center text-sm text-gray-500">
            © 2025 HealthCare Plus Clinic. All rights reserved.
          </p>
        </div>
      </footer>
    </div>
  )
}

export default App
