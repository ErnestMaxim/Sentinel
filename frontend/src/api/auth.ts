// ── Auth API ───────────────────────────────────────────────────────────────────
// All network calls for authentication flows.
// Accepts domain-level inputs, speaks DTOs to the server, returns domain types.

import type {
  LoginRequestDto,
  RegisterRequestDto,
  ForgotPasswordRequestDto,
  ResetPasswordRequestDto,
  TokenResponseDto,
  UserResponseDto,
  PatchMeRequestDto,
} from './dto/auth.dto'

const API = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api'

// ── Internal fetch helper ─────────────────────────────────────────────────────

async function post<TResponse>(path: string, body: unknown): Promise<TResponse> {
  const res  = await fetch(`${API}${path}`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(body),
  })
  const data = await res.json().catch(() => ({})) as Record<string, unknown>
  if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${res.status})`)
  return data as TResponse
}

async function patch<TResponse>(path: string, body: unknown, token: string | null): Promise<TResponse> {
  const res = await fetch(`${API}${path}`, {
    method:  'PATCH',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  })
  const data = await res.json().catch(() => ({})) as Record<string, unknown>
  if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${res.status})`)
  return data as TResponse
}

async function get<TResponse>(path: string, token: string | null): Promise<TResponse> {
  const res = await fetch(`${API}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  const data = await res.json().catch(() => ({})) as Record<string, unknown>
  if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${res.status})`)
  return data as TResponse
}

// ── Public API ────────────────────────────────────────────────────────────────

/** Returns the raw JWT access token string. Caller stores it. */
export async function login(email: string, password: string): Promise<string> {
  const dto: LoginRequestDto = { email: email.trim().toLowerCase(), password }
  const res = await post<TokenResponseDto>('/auth/login', dto)
  if (!res.access_token) throw new Error('Invalid login response: token missing.')
  return res.access_token
}

export async function register(payload: {
  firstName: string
  lastName:  string
  email:     string
  password:  string
}): Promise<void> {
  const dto: RegisterRequestDto = {
    first_name: payload.firstName.trim(),
    last_name:  payload.lastName.trim(),
    email:      payload.email.trim().toLowerCase(),
    password:   payload.password,
  }
  await post('/users/', dto)
}

export async function forgotPassword(email: string): Promise<void> {
  const dto: ForgotPasswordRequestDto = { email: email.trim().toLowerCase() }
  await post('/auth/forgot-password', dto)
}

export async function resetPassword(token: string, newPassword: string): Promise<void> {
  const dto: ResetPasswordRequestDto = { token, new_password: newPassword }
  await post('/auth/reset-password', dto)
}

/** Returns the raw UserResponseDto — AuthProvider maps it to AuthUser. */
export async function fetchMe(token: string): Promise<UserResponseDto> {
  return get<UserResponseDto>('/auth/me', token)
}

export async function patchMe(payload: {
  first_name?:       string | null
  last_name?:        string | null
  current_password?: string | null
  new_password?:     string | null
}): Promise<UserResponseDto> {
  const dto: PatchMeRequestDto = payload
  const token = localStorage.getItem('access_token')
  return patch<UserResponseDto>('/auth/me', dto, token)
}

export function redirectToGoogle(): void {
  window.location.href = `${API}/auth/google`
}
