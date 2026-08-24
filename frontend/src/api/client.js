/** Optional REST boundary for the MedSync edge node. */

const API_URL = (import.meta.env.VITE_MEDSYNC_API_URL || "http://localhost:8000").replace(/\/$/, "")

export const backendConfigured = Boolean(API_URL)

function endpoint(path) {
  return `${API_URL}${path.startsWith("/") ? path : `/${path}`}`
}

async function request(path, options = {}) {
  if (!backendConfigured) {
    throw new Error("MedSync backend is not configured")
  }

  const role = path.startsWith("/queue") ? "Receptionist" : "Doctor"

  const response = await fetch(endpoint(path), {
    ...options,
    headers: {
      Accept: "application/json",
      "X-Role": role,
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
  baseURL: API_URL,
  isConfigured: () => backendConfigured,
  getQueue: () => request("/queue/today"),
  seedQueue: () => request("/queue/seed", { method: "POST" }),
  selectToken: (tokenNumber) => request(`/encounter/${tokenNumber}/select`, {
    method: "POST",
    body: JSON.stringify({ token_number: tokenNumber }),
  }),
  resetEncounter: (tokenNumber) => request(`/encounter/${tokenNumber}/reset`, {
    method: "POST",
  }),
  processText: (tokenNumber, { text, language }) => request(`/encounter/${tokenNumber}/transcript`, {

    method: "POST",
    body: JSON.stringify({ text, language }),
  }),
  finishEncounter: (tokenNumber, { text, language } = {}) => request(`/encounter/${tokenNumber}/finalize`, {
    method: "POST",
    body: JSON.stringify({ text, language }),
  }),
  fetchRecord: (tokenNumber) => request(`/encounter/${tokenNumber}/record`),
}

export function pipelineStreamUrl() {
  return backendConfigured ? endpoint("/events/stream") : null
}
