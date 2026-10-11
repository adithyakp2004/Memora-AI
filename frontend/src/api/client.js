class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

function validationMessage(errors) {
  if (!Array.isArray(errors)) {
    return 'Please check your details and try again.'
  }

  const messages = errors.map((error) => {
    const field = Array.isArray(error.loc) ? error.loc.at(-1) : ''
    if (field === 'email') return 'Enter a valid email address.'
    if (field === 'password') return 'Use a password between 8 and 128 characters.'
    if (field === 'full_name') return 'Enter your name (up to 120 characters).'
    return 'Please check your details and try again.'
  })

  return [...new Set(messages)].join(' ')
}

async function request(path, { token, ...options } = {}) {
  const headers = new Headers(options.headers)
  if (
    options.body &&
    !(options.body instanceof FormData) &&
    !headers.has('Content-Type')
  ) {
    headers.set('Content-Type', 'application/json')
  }
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  let response
  try {
    response = await fetch(path, { ...options, headers })
  } catch {
    throw new ApiError('The server could not be reached. Please try again.', 0)
  }

  let result
  try {
    result = await response.json()
  } catch {
    result = null
  }

  if (!response.ok) {
    const detail = result?.detail
    const message =
      response.status === 503 && typeof detail === 'string'
        ? detail
        : response.status >= 500
        ? 'A server error prevented the request. Please try again.'
        : typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? validationMessage(detail)
          : 'The request could not be completed. Please try again.'
    throw new ApiError(message, response.status)
  }

  return result
}

export const api = {
  register: (details) =>
    request('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify(details),
    }),
  login: (credentials) =>
    request('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify(credentials),
    }),
  currentUser: (token) => request('/api/auth/me', { token }),
  documents: {
    list: (token) => request('/api/documents?limit=100', { token }),
    upload: (token, file) => {
      const form = new FormData()
      form.append('file', file)
      return request('/api/documents/upload', {
        method: 'POST',
        token,
        body: form,
      })
    },
    content: (token, documentId) =>
      request(`/api/documents/${encodeURIComponent(documentId)}/content`, {
        token,
      }),
    reindex: (token, documentId) =>
      request(`/api/documents/${encodeURIComponent(documentId)}/reindex`, {
        method: 'POST',
        token,
      }),
    delete: (token, documentId) =>
      request(`/api/documents/${encodeURIComponent(documentId)}`, {
        method: 'DELETE',
        token,
      }),
  },
  search: (token, query, limit = 5) =>
    request('/api/search', {
      method: 'POST',
      token,
      body: JSON.stringify({ query, limit }),
    }),
}

export { ApiError }
