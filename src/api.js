const API_BASE = '/api'

function readableError(detail) {
  if (!detail) return '请求失败，请稍后重试'
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map(item => readableError(item?.msg || item)).filter(Boolean).join('；')
  }
  if (typeof detail === 'object') {
    const message = readableError(detail.message || detail.msg || detail.error || '')
    const extra = Array.isArray(detail.details)
      ? detail.details.map(item => readableError(item)).filter(Boolean).join('；')
      : ''
    if (message && message !== '请求失败，请稍后重试') return extra ? `${message}：${extra}` : message
    try { return JSON.stringify(detail) } catch { return '请求失败，请稍后重试' }
  }
  return String(detail)
}

export function getToken() {
  return localStorage.getItem('syncmate_token')
}

export function setToken(token) {
  if (token) localStorage.setItem('syncmate_token', token)
  else localStorage.removeItem('syncmate_token')
}

export async function api(path, options = {}) {
  const token = getToken()
  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  })
  if (response.status === 204) return null
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(readableError(data.detail || data.message))
  return data
}
