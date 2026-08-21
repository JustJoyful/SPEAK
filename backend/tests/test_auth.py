import os
import pytest
from fastapi.testclient import TestClient
from backend.routes.reception import router
from fastapi import FastAPI

app = FastAPI()
app.include_router(router)

client = TestClient(app)

def test_reception_requires_auth():
    # Attempting to seed without auth should fail
    response = client.post("/queue/seed")
    assert response.status_code == 403
    assert "Forbidden: Receptionist privileges required to perform this action." in response.json()["detail"]

def test_reception_with_auth_success():
    # Attempting to seed with the correct Receptionist header should succeed
    response = client.post("/queue/seed", headers={"X-Role": "Receptionist"})
    assert response.status_code == 200
    assert len(response.json()) > 0
