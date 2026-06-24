import type { UserResponseDto } from '../dto/auth.dto'
import type { AuthUser }        from '../../context/AuthContext'

function buildInitials(firstName: string, lastName: string, email: string): string {
  const f = firstName.trim().charAt(0).toUpperCase()
  const l = lastName.trim().charAt(0).toUpperCase()
  if (f && l) return `${f}${l}`
  if (f)      return f
  return email.charAt(0).toUpperCase() || '?'
}

export function mapUserDto(dto: UserResponseDto): AuthUser {
  const storedIcon = localStorage.getItem('sentinel-user-icon') ?? undefined
  return {
    email:     dto.email,
    firstName: dto.first_name,
    lastName:  dto.last_name,
    initials:  buildInitials(dto.first_name, dto.last_name, dto.email),
    avatar:    storedIcon,
  }
}
