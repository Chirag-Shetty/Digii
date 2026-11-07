import os
from typing import Optional
from fastapi import Header, HTTPException, status


def get_staff_key(x_staff_key: Optional[str] = Header(None, alias="X-Staff-Key")) -> str:
    """
    Validates X-Staff-Key header against STAFF_KEY env var (default 'dev-key').
    NOTE: This lightweight header token is a stand-in for real campus auth / SSO.
    """
    expected_key = os.getenv("STAFF_KEY", "dev-key")
    if not x_staff_key or x_staff_key != expected_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Missing or invalid X-Staff-Key header. (Stand-in for real auth)",
        )
    return x_staff_key
