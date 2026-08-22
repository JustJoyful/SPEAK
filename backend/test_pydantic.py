import asyncio
from pipeline.llm_structurer import sadiesink, FHIROPConsultRecord

async def test_validation():
    import backend.pipeline.llm_structurer as structurer
    
    # Mock the LLM call
    async def mock_sadiesink(*args, **kwargs):
        # Return a valid dict simulating JSON response from LLM
        parsed = {
            "chief_complaints": ["Fever"],
            "vitals": [{"vital_name": "Temperature", "value": "101 F"}],
            "diagnoses": [
                {
                    "clinical_status": "active",
                    "verification_status": "provisional",
                    "code": {"coding": [], "text": "Fever"}
                }
            ],
            "medications": [
                {
                    "medication": "Paracetamol",
                    "dosage": {"timing": "TDS", "duration": "3 days", "route": "oral", "instructions": "after food"}
                }
            ],
            "advice_and_followup": "Rest"
        }
        parsed = structurer.inject_care_context(parsed, "test-context")
        record = FHIROPConsultRecord.model_validate(parsed)
        return record, ""
        
    structurer.sadiesink = mock_sadiesink
    
    record, err = await structurer.sadiesink("Test clinical text", "test-context", "dummy_key")
    if err:
        print("Error:", err)
    else:
        print("Pydantic validation successful! Output:")
        print(record.model_dump_json(indent=2))

asyncio.run(test_validation())
