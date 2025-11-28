function AppointmentConfirmation({ appointment }) {
  if (!appointment) return null

  const formatDate = (dateStr) => {
    if (!dateStr) return 'N/A'
    try {
      const date = new Date(dateStr)
      return date.toLocaleDateString('en-US', {
        weekday: 'long',
        year: 'numeric',
        month: 'long',
        day: 'numeric'
      })
    } catch {
      return dateStr
    }
  }

  const formatTime = (timeStr) => {
    if (!timeStr) return 'N/A'
    try {
      const [hours, minutes] = timeStr.split(':')
      const hour = parseInt(hours)
      const ampm = hour >= 12 ? 'PM' : 'AM'
      const hour12 = hour % 12 || 12
      return `${hour12}:${minutes} ${ampm}`
    } catch {
      return timeStr
    }
  }

  return (
    <div className="bg-gradient-to-br from-green-50 to-green-100 rounded-xl shadow-sm border border-green-200 p-6">
      {/* Success Icon */}
      <div className="flex items-center justify-center mb-4">
        <div className="w-16 h-16 bg-green-500 rounded-full flex items-center justify-center">
          <svg className="w-8 h-8 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
        </div>
      </div>

      <h3 className="text-lg font-bold text-green-800 text-center mb-4">
        Appointment Confirmed!
      </h3>

      <div className="space-y-3 text-sm">
        <div className="flex items-start space-x-3">
          <svg className="w-5 h-5 text-green-600 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
          </svg>
          <div>
            <p className="font-medium text-gray-700">Date</p>
            <p className="text-gray-600">{formatDate(appointment.date)}</p>
          </div>
        </div>

        <div className="flex items-start space-x-3">
          <svg className="w-5 h-5 text-green-600 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <div>
            <p className="font-medium text-gray-700">Time</p>
            <p className="text-gray-600">{formatTime(appointment.time)}</p>
          </div>
        </div>

        {appointment.confirmationCode && (
          <div className="flex items-start space-x-3">
            <svg className="w-5 h-5 text-green-600 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
            </svg>
            <div>
              <p className="font-medium text-gray-700">Confirmation Code</p>
              <p className="text-gray-600 font-mono bg-white px-2 py-1 rounded inline-block">
                {appointment.confirmationCode}
              </p>
            </div>
          </div>
        )}
      </div>

      <div className="mt-4 p-3 bg-white rounded-lg border border-green-200">
        <p className="text-xs text-gray-500">
          <strong>Reminder:</strong> Please arrive 15 minutes early for your appointment. 
          Don't forget to bring your ID and insurance card.
        </p>
      </div>

      <div className="mt-4 flex space-x-2">
        <button 
          className="flex-1 px-3 py-2 text-sm bg-white text-green-700 border border-green-300 rounded-lg hover:bg-green-50 transition-colors"
          onClick={() => {
            // TODO: Implement add to calendar
            alert('Add to calendar feature coming soon!')
          }}
        >
          📅 Add to Calendar
        </button>
        <button 
          className="flex-1 px-3 py-2 text-sm bg-white text-green-700 border border-green-300 rounded-lg hover:bg-green-50 transition-colors"
          onClick={() => {
            // TODO: Implement print
            window.print()
          }}
        >
          🖨️ Print
        </button>
      </div>
    </div>
  )
}

export default AppointmentConfirmation
