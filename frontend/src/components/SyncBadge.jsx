import { CloudOff, Cloud, Loader2 } from "lucide-react"
import { cn } from "@/lib/utils"

export function SyncBadge({ backendConfigured, online, loading, error, pendingCount }) {
  const pending = Number.isFinite(pendingCount) && pendingCount > 0 ? pendingCount : null
  const isLocal = !backendConfigured
  const isOffline = backendConfigured && !online
  const isLoading = backendConfigured && online && loading
  const isError = backendConfigured && online && !loading && Boolean(error)
  const label = isLocal
    ? "Local demo"
    : isOffline
      ? "Offline"
      : isLoading
      ? "Connecting"
      : isError
        ? "Edge unavailable"
        : pending
          ? `${pending} pending sync${pending === 1 ? "" : "s"}`
          : online
            ? "Edge connected"
            : "Offline"

  return (
    <div
      className={cn(
        "flex items-center gap-1.5 rounded-full border px-2.5 py-1.5 text-[0.68rem] font-medium",
        isError || isOffline ? "border-rejected/25 bg-rejected/10 text-rejected" : "border-teal/20 bg-teal-soft text-teal",
      )}
      title={isLocal ? "Backend mode is disabled; using the local demonstration pipeline" : label}
      role="status"
      aria-live="polite"
    >
      {isLoading ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" /> : isLocal || online ? <Cloud className="h-3 w-3" aria-hidden="true" /> : <CloudOff className="h-3 w-3" aria-hidden="true" />}
      <span>{label}</span>
    </div>
  )
}
