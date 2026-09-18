import pytest
from app.browser_agent import BrowserSafetyError,close_session,create_session,fill_control,inspect_session

@pytest.mark.asyncio
async def test_local_demo_browser_can_inspect_and_fill_non_submit_controls():
    session=await create_session("demo-browser-user","http://localhost:5000/")
    try:
        inspection=await inspect_session(session)
        by_name={c.get("name"):c for c in inspection["controls"] if c.get("name")}
        assert {"fullName","dob","email","mobile","captcha","otp"}.issubset(by_name)
        await fill_control(session,by_name["fullName"]["index"],"Test Candidate")
        await fill_control(session,by_name["email"]["index"],"test@example.com")
        submit=next(c for c in inspection["controls"] if c.get("type")=="submit")
        with pytest.raises(BrowserSafetyError):
            await fill_control(session,submit["index"],"anything")
        assert inspection["submission_allowed"] is False
    finally:
        await close_session(session.session_id,"demo-browser-user")
