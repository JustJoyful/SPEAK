from fastapi import Header, HTTPException
from typing import Optional


def verify_receptionist(x_role: Optional[str] = Header(None, alias="X-Role")):
    """
    Mock Dependency Injection to enforce that the caller has 'Receptionist' privileges.
    In a real system, this would decode a JWT or query an IAM provider.
    """
    if not x_role or x_role.lower() != "receptionist":
        raise HTTPException(
            status_code=403, 
            detail="Forbidden: Receptionist privileges required to perform this action."
        )


def verify_doctor(x_role: Optional[str] = Header(None, alias="X-Role")):
    """
    Mock Dependency Injection to enforce that the caller has 'Doctor' privileges.
    """
    if not x_role or x_role.lower() != "doctor":
        raise HTTPException(
            status_code=403, 
            detail="Forbidden: Doctor privileges required to perform this action."
        )
