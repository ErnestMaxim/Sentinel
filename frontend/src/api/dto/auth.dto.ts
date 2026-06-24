// ── Requests ──────────────────────────────────────────────────────────────────
export interface LoginRequestDto {
  email:    string
  password: string
}

export interface RegisterRequestDto {
  first_name: string
  last_name:  string
  email:      string
  password:   string
}

export interface ForgotPasswordRequestDto {
  email: string
}

export interface ResetPasswordRequestDto {
  token:        string
  new_password: string
}

export interface PatchMeRequestDto {
  first_name?:       string | null
  last_name?:        string | null
  current_password?: string | null
  new_password?:     string | null
}

// ── Responses ─────────────────────────────────────────────────────────────────
export interface TokenResponseDto {
  access_token: string
  token_type:   string
}

export interface UserResponseDto {
  id:         number
  first_name: string
  last_name:  string
  email:      string
  created_at: string
  is_deleted: boolean
}
