// ── Settings page API ──────────────────────────────────────────────────────────
// Thin wrapper around PATCH /auth/me.
// Re-exports from the shared api/auth module — settings owns no network logic.

export { patchMe } from '../../api/auth'
export type { PatchMeRequestDto as PatchMePayload } from '../../api/dto/auth.dto'
