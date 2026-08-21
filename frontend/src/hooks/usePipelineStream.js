import { useEffect, useRef, useState } from "react"
import { pipelineStreamUrl } from "@/api/client"

/** Subscribe to pipeline SSE events when an edge-node URL is configured. */
export function usePipelineStream({ enabled = true, onEvent } = {}) {
  const [connection, setConnection] = useState("disabled")
  const onEventRef = useRef(onEvent)
  onEventRef.current = onEvent

  useEffect(() => {
    const streamUrl = enabled ? pipelineStreamUrl() : null
    if (!streamUrl || typeof window === "undefined" || !window.EventSource) {
      setConnection(streamUrl ? "unsupported" : "disabled")
      return undefined
    }

    const source = new EventSource(streamUrl)
    setConnection("connecting")
    source.onopen = () => setConnection("connected")
    source.onerror = () => setConnection("disconnected")
    source.onmessage = (event) => {
      try {
        onEventRef.current?.(JSON.parse(event.data))
      } catch {
        onEventRef.current?.({ type: "message", data: event.data })
      }
    }

    return () => {
      source.close()
    }
  }, [enabled])

  return { connection }
}

