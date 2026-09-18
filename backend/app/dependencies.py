from fastapi import Header, HTTPException, status


async def current_user_id(x_user_id: str | None = Header(default=None)) -> str:
    """Temporary adapter boundary for auth integration in the next phase.

    Never trust this header in production. The production auth dependency must
    derive the user id from a verified session/JWT before protected routes are
    exposed.
    """
    if not x_user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required")
    return x_user_id
