import { Outlet, useLocation } from 'react-router-dom'
import Navbar from '../shared/navbar/Navbar'
import PageTransition from './PageTransition'

/**
 * Persistent shell for all authenticated/main pages.
 * Navbar mounts ONCE here and survives every route swap,
 * so the active-indicator pill can slide smoothly between items.
 *
 * PageTransition receives `key={pathname}` so React fully unmounts the
 * old instance and mounts a fresh one on each route change — this fires
 * the GSAP entrance animation for every incoming page.
 */
export default function AppLayout() {
  const { pathname } = useLocation()
  return (
    <>
      <Navbar />
      <PageTransition key={pathname}>
        <Outlet />
      </PageTransition>
    </>
  )
}
