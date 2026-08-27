const API_BASE = '/api'

export function getToken() {
  return localStorage.getItem('syncmate_token')
}

export function setToken(token) {
  if (token) localStorage.setItem('syncmate_token', token)
  else localStorage.removeItem('syncmate_token')
}

export async function api(path, options = {}) {
  const token = getToken()
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  })
  if (response.status === 204) return null
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.detail || '请求失败，请稍后重试')
  return data
}
