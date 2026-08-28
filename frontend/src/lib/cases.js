import CASES_DATA from "../patients.json"

export const CASES = CASES_DATA

export const CHECKLIST_LABELS = {
  symptoms: "Symptoms",
  diagnosis: "Diagnosis",
  medication: "Medication",
  advice: "Advice",
}

export const CHECKLIST_ORDER = ["symptoms", "diagnosis", "medication", "advice"]

export const SYMPTOM_PATTERN = /\b(fever|chills|cough|cold|headache|pain|chest\s+pain|body\s+ache|vomit|nausea|dizzy|dizziness|fatigue|weakness|breathless|shortness\s+of\s+breath|throat|sore\s+throat|rash|swelling|burning|itching|paraesthesia|polydipsia|thirst|ache|wheeze|lesion|wound)\b/i
export const DIAGNOSIS_PATTERN = /\b(hypertension|diabetes|dengue|malaria|typhoid|asthma|bronchitis|pneumonia|infection|gastritis|gerd|copd|arthritis|migraine|anaemia|anemia|tuberculosis|tb|uti|illness|febrile|neuropathy|t2dm|t1dm)\b/i
export const MEDICATION_PATTERN = /\b(dolo|paracetamol|pcm|metformin|amlodipine|pantocid|pantoprazole|augmentin|amoxicillin|azithromycin|cetirizine|salbutamol|budesonide|pregabalin|ors|tab|tablet|syrup|inhaler|capsule|mg|mcg|tds|bd|od|hs|prn|sos|dosage|dose|drops)\b/i
export const ADVICE_PATTERN = /\b(rest|fluid|fluids|water|diet|exercise|avoid|salt|sugar|review|follow\s*up|consult|admitted|hospital|investigation|test|cbc|ecg|blood\s+test|warm\s+water|days|hours|weeks|month|inspection|hba1c|creatinine)\b/i

export function extractClinicalChecklist(text) {
  if (!text || typeof text !== "string" || !text.trim()) return {}
  return {
    symptoms: SYMPTOM_PATTERN.test(text) ? "checked" : "empty",
    diagnosis: DIAGNOSIS_PATTERN.test(text) ? "checked" : "empty",
    medication: MEDICATION_PATTERN.test(text) ? "checked" : "empty",
    advice: ADVICE_PATTERN.test(text) ? "checked" : "empty",
  }
}

export function normalizeChecklistState(raw) {
  if (!raw || typeof raw !== "object") return {}
  const result = {}
  for (const k of CHECKLIST_ORDER) {
    const presentKey = `${k}_present`
    const isPresent = raw[presentKey] === true || raw[k] === "checked" || raw[k] === true
    if (isPresent) {
      result[k] = "checked"
    } else if (raw[k] === "filling") {
      result[k] = "filling"
    }
  }
  return result
}

export function mergeChecklistState(current = {}, incoming = {}) {
  const normalized = normalizeChecklistState(incoming)
  const merged = { ...current }
  for (const k of CHECKLIST_ORDER) {
    if (current[k] === "checked") {
      merged[k] = "checked"
    } else if (normalized[k]) {
      merged[k] = normalized[k]
    }
  }
  return merged
}
