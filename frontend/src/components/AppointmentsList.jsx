import { useState, useEffect } from 'react'
import axios from 'axios'

const API_URL = 'http://localhost:8000'

function AppointmentsList() {
  const [appointments, setAppointments] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [filter, setFilter] = useState('all') // all, today, upcoming
  const [searchEmail, setSearchEmail] = useState('')

  useEffect(() => {
    fetchAppointments()
  }, [filter])

  const fetchAppointments = async () => {
    setLoading(true)
    setError(null)
    
    try {
      let url = `${API_URL}/api/calendly/appointments`
      
      if (filter === 'today') {
        const today = new Date().toISOString().split('T')[0]
        url += `?date=${today}`
      }
      
      const response = await axios.get(url)
      setAppointments(response.data.appointments || [])
    } catch (err) {
      setError('Failed to load appointments. Please try again.')
      console.error('Error fetching appointments:', err)
    } finally {
      setLoading(false)
    }
  }

  const searchByEmail = async () => {
    if (!searchEmail.trim()) {
      fetchAppointments()
      return
    }
    
    setLoading(true)
    setError(null)
    
    try {
      const response = await axios.get(`${API_URL}/api/calendly/my-appointments?email=${encodeURIComponent(searchEmail)}`)
      const allAppointments = [
        ...(response.data.upcoming_appointments || []),
        ...(response.data.past_appointments || [])
      ]
      setAppointments(allAppointments)
    } catch (err) {
      setError('Failed to search appointments. Please check the email and try again.')
      console.error('Error searching appointments:', err)
    } finally {
      setLoading(false)
    }
  }

  const formatTime = (time) => {
    const [hours, minutes] = time.split(':')
    const hour = parseInt(hours)
    const ampm = hour >= 12 ? 'PM' : 'AM'
    const hour12 = hour % 12 || 12
    return `${hour12}:${minutes} ${ampm}`
  }

  const formatDate = (dateStr) => {
    const date = new Date(dateStr)
    return date.toLocaleDateString('en-US', { 
      weekday: 'long', 
      year: 'numeric', 
      month: 'long', 
      day: 'numeric' 
    })
  }

  const getStatusColor = (status) => {
    switch (status) {
      case 'confirmed':
        return 'bg-green-100 text-green-800'
      case 'cancelled':
        return 'bg-red-100 text-red-800'
      case 'completed':
        return 'bg-blue-100 text-blue-800'
      default:
        return 'bg-gray-100 text-gray-800'
    }
  }

  const getTypeIcon = (type) => {
    switch (type) {
      case 'consultation':
        return '🩺'
      case 'followup':
        return '🔄'
      case 'physical':
        return '📋'
      case 'specialist':
        return '👨‍⚕️'
      default:
        return '📅'
    }
  }

  return (
    <div className="bg-white rounded-xl shadow-lg border border-gray-100 overflow-hidden">
      {/* Header */}
      <div className="bg-gradient-to-r from-blue-600 to-blue-700 px-6 py-4">
        <h2 className="text-xl font-bold text-white flex items-center">
          <svg className="w-6 h-6 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
          </svg>
          Booked Appointments
        </h2>
        <p className="text-blue-100 text-sm mt-1">View and manage all scheduled appointments</p>
      </div>

      {/* Filters */}
      <div className="p-4 border-b border-gray-100 bg-gray-50">
        <div className="flex flex-col sm:flex-row gap-4">
          {/* Filter Buttons */}
          <div className="flex gap-2">
            <button
              onClick={() => setFilter('all')}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                filter === 'all' 
                  ? 'bg-blue-600 text-white' 
                  : 'bg-white text-gray-700 hover:bg-gray-100 border border-gray-200'
              }`}
            >
              All
            </button>
            <button
              onClick={() => setFilter('today')}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                filter === 'today' 
                  ? 'bg-blue-600 text-white' 
                  : 'bg-white text-gray-700 hover:bg-gray-100 border border-gray-200'
              }`}
            >
              Today
            </button>
          </div>

          {/* Email Search */}
          <div className="flex-1 flex gap-2">
            <input
              type="email"
              value={searchEmail}
              onChange={(e) => setSearchEmail(e.target.value)}
              onKeyPress={(e) => e.key === 'Enter' && searchByEmail()}
              placeholder="Search by patient email..."
              className="flex-1 px-4 py-2 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
            />
            <button
              onClick={searchByEmail}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium"
            >
              Search
            </button>
            {searchEmail && (
              <button
                onClick={() => {
                  setSearchEmail('')
                  fetchAppointments()
                }}
                className="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300 transition-colors text-sm font-medium"
              >
                Clear
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="p-4">
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600"></div>
            <span className="ml-3 text-gray-600">Loading appointments...</span>
          </div>
        ) : error ? (
          <div className="text-center py-12">
            <div className="text-red-500 mb-4">
              <svg className="w-12 h-12 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <p className="text-gray-600">{error}</p>
            <button
              onClick={fetchAppointments}
              className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
            >
              Try Again
            </button>
          </div>
        ) : appointments.length === 0 ? (
          <div className="text-center py-12">
            <div className="text-gray-400 mb-4">
              <svg className="w-16 h-16 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
              </svg>
            </div>
            <p className="text-gray-600 text-lg">No appointments found</p>
            <p className="text-gray-400 text-sm mt-1">Try adjusting your filters or search criteria</p>
          </div>
        ) : (
          <div className="space-y-4">
            <p className="text-sm text-gray-500 mb-4">
              Showing {appointments.length} appointment{appointments.length !== 1 ? 's' : ''}
            </p>
            
            {appointments.map((appointment, index) => (
              <div
                key={appointment.booking_id || index}
                className="border border-gray-200 rounded-xl p-4 hover:shadow-md transition-shadow bg-white"
              >
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                  {/* Left Side - Main Info */}
                  <div className="flex items-start gap-4">
                    <div className="text-3xl">{getTypeIcon(appointment.appointment_type)}</div>
                    <div>
                      <h3 className="font-semibold text-gray-900">
                        {appointment.patient_name || 'Unknown Patient'}
                      </h3>
                      <p className="text-sm text-gray-600 mt-1">
                        {formatDate(appointment.date)}
                      </p>
                      <p className="text-sm text-blue-600 font-medium">
                        {formatTime(appointment.start_time)} - {formatTime(appointment.end_time)}
                      </p>
                      {appointment.reason && (
                        <p className="text-sm text-gray-500 mt-1">
                          Reason: {appointment.reason}
                        </p>
                      )}
                    </div>
                  </div>

                  {/* Right Side - Status & Details */}
                  <div className="flex flex-col items-end gap-2">
                    <span className={`px-3 py-1 rounded-full text-xs font-medium ${getStatusColor(appointment.status)}`}>
                      {appointment.status || 'Scheduled'}
                    </span>
                    <span className="text-xs text-gray-500 bg-gray-100 px-2 py-1 rounded">
                      {appointment.appointment_type?.replace('_', ' ') || 'Consultation'}
                    </span>
                    {appointment.confirmation_code && (
                      <span className="text-xs text-gray-400">
                        Code: {appointment.confirmation_code}
                      </span>
                    )}
                  </div>
                </div>

                {/* Contact Info */}
                {(appointment.patient_email || appointment.patient_phone) && (
                  <div className="mt-3 pt-3 border-t border-gray-100 flex flex-wrap gap-4 text-sm text-gray-500">
                    {appointment.patient_email && (
                      <span className="flex items-center gap-1">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                        </svg>
                        {appointment.patient_email}
                      </span>
                    )}
                    {appointment.patient_phone && (
                      <span className="flex items-center gap-1">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z" />
                        </svg>
                        {appointment.patient_phone}
                      </span>
                    )}
                    <span className="flex items-center gap-1">
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                      </svg>
                      {appointment.doctor_name || 'Dr. Sarah Johnson'}
                    </span>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Refresh Button */}
      <div className="p-4 border-t border-gray-100 bg-gray-50">
        <button
          onClick={fetchAppointments}
          className="w-full py-2 text-sm text-gray-600 hover:text-blue-600 transition-colors flex items-center justify-center gap-2"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          Refresh Appointments
        </button>
      </div>
    </div>
  )
}

export default AppointmentsList
