import posthog from 'posthog-js'

function capture(event: string, props?: Record<string, unknown>) {
  if (typeof window === 'undefined') return
  posthog.capture(event, props)
}

export const Analytics = {
  identify(user: { id: string; email: string; name?: string; plan?: string; gstin_count?: number }) {
    posthog.identify(user.id, { email: user.email, name: user.name, plan: user.plan, gstin_count: user.gstin_count })
  },
  reset() { posthog.reset() },

  runStarted: (period: string, source: string) => capture('reconciliation_run_started', { period, source }),
  runCompleted: (props: { period: string; matched: number; mismatched: number; pending: number; duration_s: number }) => capture('reconciliation_run_completed', props),
  runFailed: (period: string, error: string) => capture('reconciliation_run_failed', { period, error }),

  filingOpened: (type: string, period: string) => capture('filing_opened', { type, period }),
  filingSaved: (type: string, period: string) => capture('filing_saved', { type, period }),
  filingCompleted: (type: string, period: string) => capture('filing_completed', { type, period }),

  imsActionConfirmed: (action: string, count: number, period: string) => capture('ims_action_confirmed', { action, count, period }),
  tallySyncCompleted: (rows: number, skipped: number) => capture('tally_sync_completed', { rows, skipped }),

  upgradeClicked: (to_plan: string, trigger: string) => capture('upgrade_clicked', { to_plan, trigger }),
  checkoutCompleted: (plan: string) => capture('checkout_completed', { plan }),

  localeSwitched: (from: string, to: string) => capture('locale_switched', { from, to }),
  exportDownloaded: (type: string) => capture('export_downloaded', { type }),
  vendorFollowupSent: (channel: string) => capture('vendor_followup_sent', { channel }),
}
