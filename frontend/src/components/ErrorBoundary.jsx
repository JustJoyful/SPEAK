import React from "react"
import { AlertTriangle, RefreshCw } from "lucide-react"

export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, errorInfo) {
    console.error("[S.P.E.A.K. ErrorBoundary] Caught error:", error, errorInfo)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex min-h-screen items-center justify-center bg-clinical p-6">
          <div className="w-full max-w-md rounded-xl border border-clinical-line bg-clinical-surface p-6 shadow-xl">
            <div className="flex items-center gap-3 text-rejected">
              <AlertTriangle className="h-6 w-6" />
              <h2 className="text-base font-semibold text-clinical-ink">Interface Encountered an Issue</h2>
            </div>
            <p className="mt-2 text-xs leading-relaxed text-clinical-muted">
              {this.state.error?.message || "An unexpected error occurred while rendering the clinical view."}
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  this.setState({ hasError: false, error: null })
                  window.location.reload()
                }}
                className="inline-flex items-center gap-2 rounded-md bg-teal px-4 py-2 text-xs font-semibold text-white shadow-sm hover:bg-teal/90"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                Reload Application
              </button>
            </div>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
