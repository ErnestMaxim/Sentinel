import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Section      from '../../components/ui/Section'
import { useAuth }  from '../../context/AuthContext'
import { patchMe }  from './api'
import { useIconState } from './hooks/useIconState'
import IconPicker    from './components/IconPicker'
import ProfileSection from './components/ProfileSection'
import PasswordSection from './components/PasswordSection'
import styles from './SettingsPage.module.css'

type Msg = { ok: boolean; text: string }

export default function SettingsPage() {
  const { user, refreshUser, setUserIcon } = useAuth()
  const navigate = useNavigate()
  const icon     = useIconState(setUserIcon)

  const [firstNameOverride, setFirstNameOverride] = useState<string | null>(null)
  const [lastNameOverride,  setLastNameOverride]  = useState<string | null>(null)
  const firstName = firstNameOverride ?? user?.firstName ?? ''
  const lastName  = lastNameOverride  ?? user?.lastName  ?? ''
  const [profileSaving, setProfileSaving] = useState(false)
  const [profileMsg,    setProfileMsg]    = useState<Msg | null>(null)

  // Password
  const [currentPw, setCurrentPw] = useState('')
  const [newPw,     setNewPw]     = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [pwSaving,  setPwSaving]  = useState(false)
  const [pwMsg,     setPwMsg]     = useState<Msg | null>(null)

  async function handleProfileSave(e: React.FormEvent) {
    e.preventDefault()
    setProfileSaving(true); setProfileMsg(null)
    try {
      await patchMe({ first_name: firstName.trim(), last_name: lastName.trim() })
      await refreshUser()
      setFirstNameOverride(null)
      setLastNameOverride(null)
      setProfileMsg({ ok: true, text: 'Saved.' })
    } catch (err) {
      setProfileMsg({ ok: false, text: err instanceof Error ? err.message : 'Something went wrong' })
    }
    setProfileSaving(false)
  }

  async function handlePasswordSave(e: React.FormEvent) {
    e.preventDefault()
    setPwMsg(null)
    if (newPw.length < 8)    { setPwMsg({ ok: false, text: 'Password must be at least 8 characters.' }); return }
    if (newPw !== confirmPw) { setPwMsg({ ok: false, text: 'Passwords do not match.' }); return }
    setPwSaving(true)
    try {
      await patchMe({ current_password: currentPw || null, new_password: newPw })
      setCurrentPw(''); setNewPw(''); setConfirmPw('')
      setPwMsg({ ok: true, text: 'Password updated.' })
    } catch (err) {
      setPwMsg({ ok: false, text: err instanceof Error ? err.message : 'Something went wrong' })
    }
    setPwSaving(false)
  }

  return (
    <div className={styles.page}>
      <main className={styles.main}>

        <div className={styles.header}>
          <button type="button" className={styles.backBtn} onClick={() => navigate(-1)}>← Back</button>
          <h1 className={styles.title}>Account settings</h1>
          <p className={styles.titleSub}>Manage your profile, avatar, and security preferences.</p>
        </div>

        <div className={styles.sections}>
          <Section title="Profile icon" desc="Choose a built-in icon, upload your own photo, or use your initials.">
            <IconPicker icon={icon} initials={user?.initials ?? '?'} />
          </Section>

          <Section title="Profile" desc="Your name appears in the sidebar and on generated reports.">
            <ProfileSection
              user={user}
              firstName={firstName}   onFirstName={v => setFirstNameOverride(v)}
              lastName={lastName}     onLastName={v => setLastNameOverride(v)}
              saving={profileSaving}  msg={profileMsg}
              onSubmit={handleProfileSave}
            />
          </Section>

          <Section title="Password" desc="Google accounts can leave the current password blank.">
            <PasswordSection
              currentPw={currentPw}   onCurrentPw={setCurrentPw}
              newPw={newPw}           onNewPw={setNewPw}
              confirmPw={confirmPw}   onConfirmPw={setConfirmPw}
              saving={pwSaving}       msg={pwMsg}
              onSubmit={handlePasswordSave}
            />
          </Section>
        </div>

      </main>
    </div>
  )
}
