export const CASES = [
  {
    token: 12,
    name: "Rahul",
    age: 34,
    sex: "M",
    complaint: "Fever, 3 days",
    status: "in-progress",
    script:
      "Patient Rahul Sharma, thirty four year old male, presents with high grade fever for three days, associated chills and body ache. No cough, no breathlessness. Temperature one hundred and one point four Fahrenheit, pulse ninety two, blood pressure one eighteen over seventy six. Throat mildly congested, chest clear on auscultation. Impression: acute viral febrile illness, dengue not ruled out. Advise paracetamol six fifty milligrams three times a day after food for three days, oral rehydration, and complete blood count with dengue NS1 today. Callback number nine eight seven six five four three two one zero. Review after forty eight hours or earlier if bleeding or persistent vomiting.",
    pii: [
      { raw: "Rahul Sharma", hash: "HASH_7A9B", kind: "NAME" },
      { raw: "nine eight seven six five four three two one zero", hash: "HASH_C4E1", kind: "PHONE" },
    ],
    marks: { symptoms: 22, diagnosis: 62, medication: 84, advice: 118 },
    fhir: {
      symptoms: ["High grade fever ×3 days", "Chills, myalgia", "No cough / no dyspnoea"],
      diagnosis: "Acute viral febrile illness — r/o dengue",
      code: "ICD-10 · A97.0",
      medication: ["Paracetamol 650 mg · TDS · PC · 3 days", "ORS sachets · ad lib"],
      advice: ["CBC + Dengue NS1 today", "Review in 48 h", "Red flags: bleeding, vomiting"],
    },
  },
  {
    token: 13,
    name: "Meena",
    age: 52,
    sex: "F",
    complaint: "Follow-up, diabetes",
    status: "waiting",
    script:
      "Patient Meena Devi, fifty two year old female, known type two diabetes for eight years, comes for routine follow up. Reports tingling of both feet at night and increased thirst. On metformin five hundred twice daily, compliance good. Fasting sugar one hundred and sixty eight, random two twenty four, weight sixty eight kilograms. Feet examined, no ulcer, protective sensation reduced on left great toe. Impression: type two diabetes mellitus, suboptimal control with early peripheral neuropathy. Advise metformin increased to one thousand milligrams twice daily, add tablet pregabalin seventy five milligrams at night. Order HbA1c and serum creatinine. Diet counselling done, daily foot inspection advised. Residing at ward four Kolar village, contact eight eight two three one one nine zero four five. Review in one month.",
    pii: [
      { raw: "Meena Devi", hash: "HASH_2F60", kind: "NAME" },
      { raw: "ward four Kolar village", hash: "HASH_B812", kind: "ADDRESS" },
      { raw: "eight eight two three one one nine zero four five", hash: "HASH_9D3C", kind: "PHONE" },
    ],
    marks: { symptoms: 28, diagnosis: 74, medication: 96, advice: 128 },
    fhir: {
      symptoms: ["Nocturnal paraesthesia both feet", "Polydipsia", "FBS 168 / RBS 224 mg/dL"],
      diagnosis: "T2DM — suboptimal control, early neuropathy",
      code: "ICD-10 · E11.42",
      medication: ["Metformin 1000 mg · BD", "Pregabalin 75 mg · HS"],
      advice: ["HbA1c + S. creatinine", "Daily foot inspection", "Review in 1 month"],
    },
  },
  {
    token: 14,
    name: "Arjun",
    age: 7,
    sex: "M",
    complaint: "Cough, wheeze",
    status: "waiting",
    script:
      "Patient Arjun Kumar, seven year old male, brought by mother with dry cough and night time wheeze for five days, worse after playing outdoors. Two similar episodes last year. Afebrile, respiratory rate twenty six, saturation ninety seven percent on room air, bilateral expiratory wheeze present. No chest indrawing. Impression: mild episodic childhood asthma, triggered by exertion and dust. Advise salbutamol inhaler two puffs with spacer as needed, budesonide inhaler one hundred micrograms twice daily for four weeks. Mother counselled on spacer technique and trigger avoidance. Mother's mobile seven seven four five six two two one eight nine. Review after two weeks with symptom diary.",
    pii: [
      { raw: "Arjun Kumar", hash: "HASH_5E18", kind: "NAME" },
      { raw: "seven seven four five six two two one eight nine", hash: "HASH_A03F", kind: "PHONE" },
    ],
    marks: { symptoms: 26, diagnosis: 66, medication: 88, advice: 112 },
    fhir: {
      symptoms: ["Dry cough + nocturnal wheeze ×5 days", "Exertional trigger", "SpO₂ 97% RA, RR 26"],
      diagnosis: "Mild episodic asthma (childhood)",
      code: "ICD-10 · J45.20",
      medication: ["Salbutamol MDI 2 puffs · PRN + spacer", "Budesonide 100 mcg · BD · 4 wk"],
      advice: ["Spacer technique demo", "Dust trigger avoidance", "Review 2 wk w/ diary"],
    },
  },
  {
    token: 15,
    name: "Lakshmi",
    age: 28,
    sex: "F",
    complaint: "ANC visit 2",
    status: "waiting",
    script:
      "Patient Lakshmi Bai, twenty eight year old female, second antenatal visit at twenty four weeks gestation, gravida two para one. Reports mild pedal oedema and occasional heartburn, no headache or blurring of vision. Blood pressure one hundred and twenty over seventy eight, weight fifty six kilograms, fundal height corresponds to dates, fetal heart rate one forty two per minute. Haemoglobin ten point two grams per decilitre. Impression: normal ongoing pregnancy with mild anaemia. Advise iron folic acid one tablet daily and calcium five hundred milligrams twice daily, continue for the remainder of pregnancy. Order urine routine and oral glucose tolerance test. Counselled on danger signs and institutional delivery. Aadhaar two three four five six seven eight nine zero one two. Next visit in four weeks.",
    pii: [
      { raw: "Lakshmi Bai", hash: "HASH_C711", kind: "NAME" },
      { raw: "two three four five six seven eight nine zero one two", hash: "HASH_44D8", kind: "AADHAAR" },
    ],
    marks: { symptoms: 30, diagnosis: 78, medication: 96, advice: 124 },
    fhir: {
      symptoms: ["Mild pedal oedema", "Heartburn", "Hb 10.2 g/dL · FHR 142 bpm"],
      diagnosis: "Normal pregnancy @24 wk with mild anaemia",
      code: "ICD-10 · O99.011",
      medication: ["IFA 1 tab · OD", "Calcium 500 mg · BD"],
      advice: ["Urine routine + OGTT", "Danger-sign counselling", "Next ANC in 4 wk"],
    },
  },
  {
    token: 16,
    name: "Ibrahim",
    age: 61,
    sex: "M",
    complaint: "Chest tightness",
    status: "waiting",
    script:
      "Patient Ibrahim Sheikh, sixty one year old male, complains of chest tightness on walking uphill for two weeks, relieved by rest within five minutes. Known hypertensive on amlodipine five milligrams, smoker twenty pack years. No pain at rest, no syncope. Blood pressure one forty six over eighty eight, pulse seventy eight regular, chest clear, no murmurs. Electrocardiogram shows T wave flattening in lateral leads. Impression: stable exertional angina, high cardiovascular risk. Advise aspirin seventy five milligrams daily, atorvastatin twenty milligrams at night, continue amlodipine, sorbitrate sublingual for chest pain. Refer to district hospital cardiology within one week for stress testing. Smoking cessation counselling given. Contact nine four four one two seven six five three zero. Return immediately if pain at rest.",
    pii: [
      { raw: "Ibrahim Sheikh", hash: "HASH_D2A5", kind: "NAME" },
      { raw: "nine four four one two seven six five three zero", hash: "HASH_61BE", kind: "PHONE" },
    ],
    marks: { symptoms: 26, diagnosis: 80, medication: 104, advice: 132 },
    fhir: {
      symptoms: ["Exertional chest tightness ×2 wk", "Relieved by rest <5 min", "ECG: lateral T flattening"],
      diagnosis: "Stable exertional angina — high CV risk",
      code: "ICD-10 · I20.8",
      medication: ["Aspirin 75 mg · OD", "Atorvastatin 20 mg · HS", "Sorbitrate 5 mg · SL PRN"],
      advice: ["Cardiology referral ≤1 wk", "Smoking cessation", "Return if rest pain"],
    },
  },
  {
    token: 17,
    name: "Sunita",
    age: 45,
    sex: "F",
    complaint: "Joint pain",
    status: "waiting",
    script:
      "Patient Sunita Rani, forty five year old female, reports pain and morning stiffness of both wrists and finger joints for three months, stiffness lasting nearly an hour. Difficulty gripping utensils. No rash, no oral ulcers. Tenderness with mild swelling of metacarpophalangeal joints bilaterally, no deformity. Impression: inflammatory polyarthritis, rheumatoid arthritis suspected. Advise naproxen two fifty milligrams twice daily after food for seven days. Order rheumatoid factor, anti CCP, and erythrocyte sedimentation rate. Refer to medicine outpatient for disease modifying therapy. Review with reports in ten days.",
    pii: [{ raw: "Sunita Rani", hash: "HASH_8B3D", kind: "NAME" }],
    marks: { symptoms: 30, diagnosis: 66, medication: 80, advice: 104 },
    fhir: {
      symptoms: ["Symmetric wrist + MCP pain ×3 mo", "Morning stiffness ~60 min", "Grip weakness"],
      diagnosis: "Inflammatory polyarthritis — ? rheumatoid",
      code: "ICD-10 · M06.9",
      medication: ["Naproxen 250 mg · BD · PC · 7 days"],
      advice: ["RF + anti-CCP + ESR", "Medicine OPD referral", "Review in 10 days"],
    },
  },
]

export const CHECKLIST_LABELS = {
  symptoms: "Symptoms",
  diagnosis: "Diagnosis",
  medication: "Medication",
  advice: "Advice",
}

export const CHECKLIST_ORDER = ["symptoms", "diagnosis", "medication", "advice"]
