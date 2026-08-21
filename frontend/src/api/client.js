/** Optional REST boundary for the MedSync edge node. */

const API_URL = (import.meta.env.VITE_MEDSYNC_API_URL || "").replace(/\/$/, "")

export const backendConfigured = Boolean(API_URL)

function endpoint(path) {
  return `${API_URL}${path.startsWith("/") ? path : `/${path}`}`
}

async function request(path, options = {}) {
  if (!backendConfigured) {
    throw new Error("MedSync backend is not configured")
  }

  const response = await fetch(endpoint(path), {
    ...options,
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  })

  if (!response.ok) {
    let detail = "Request failed"
    try {
      const body = await response.json()
      detail = body.detail || body.message || detail
    } catch {
      // Keep the HTTP status when the server does not return JSON.
    }
    throw new Error(`${response.status}: ${detail}`)
  }

  return response.status === 204 ? null : response.json()
}

export const medSyncApi = {
  isConfigured: () => backendConfigured,
  getQueue: () => request("/queue/today"),
  seedQueue: () => request("/queue/seed", { method: "POST" }),
  selectToken: (tokenNumber) => request("/encounter/select-token", {
    method: "POST",
    body: JSON.stringify({ token_number: tokenNumber }),
  }),
  processText: ({ text, language }) => request("/encounter/text", {
    method: "POST",
    body: JSON.stringify({ text, language }),
  }),
  finishEncounter: ({ text, language } = {}) => request("/encounter/finish", {
    method: "POST",
    body: JSON.stringify({ text, language }),
  }),
}

export function pipelineStreamUrl() {
  return backendConfigured ? endpoint("/events/stream") : null
}

