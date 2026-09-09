import { Component, type ReactNode } from 'react'

declare global {
  interface Window {
    AeroOpsReporter?: { report: (error: unknown, info?: { componentStack?: string }) => void }
  }
}

type Props = {
  children: ReactNode
  /** Shown instead of the crashed tree. Keep it static — it must never throw. */
  fallback?: ReactNode
  onCatch?: (error: unknown) => void
}

/**
 * Drop-in React Error Boundary wired to the AeroOps reporter.
 *
 *   import { AeroErrorBoundary } from './AeroErrorBoundary'
 *   <AeroErrorBoundary><App /></AeroErrorBoundary>
 *
 * Requires aeroops-reporter.js loaded + init() already called.
 */
export class AeroErrorBoundary extends Component<Props, { crashed: boolean }> {
  state = { crashed: false }

  static getDerivedStateFromError(): { crashed: boolean } {
    return { crashed: true }
  }

  componentDidCatch(error: unknown, info: { componentStack?: string }): void {
    try {
      window.AeroOpsReporter?.report(error, info)
    } catch {
      /* telemetry must never break the host app */
    }
    try {
      this.props.onCatch?.(error)
    } catch {
      /* host callback errors are swallowed on purpose */
    }
  }

  render(): ReactNode {
    if (this.state.crashed) {
      return (
        this.props.fallback ?? (
          <div style={{ padding: 24, fontFamily: 'system-ui, sans-serif' }}>
            <h2>Something went wrong.</h2>
            <p>The error was reported automatically. Please reload the page.</p>
          </div>
        )
      )
    }
    return this.props.children
  }
}
