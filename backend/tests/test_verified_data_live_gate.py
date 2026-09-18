from unittest.mock import AsyncMock

import pytest

from app.live_browser import LiveBrowserManager
from app.verified_data_service import VerifiedDataResult, VerifiedDataStatus


@pytest.mark.asyncio
async def test_verified_data_conflict_pushes_human_required_and_unlocks():
    manager = LiveBrowserManager()
    websocket = AsyncMock()
    session_id = "session-1"
    manager._channels[session_id] = websocket
    manager._channel_users[session_id] = "user-1"

    result = VerifiedDataResult(
        status=VerifiedDataStatus.CONFLICT,
        field_key="full_name",
        message="multiple verified values found",
    )
    await manager.require_human_for_verified_data(session_id, "full_name", result)

    control = manager._controls[session_id]
    assert control.control == "unlocked"
    assert control.mode == "human"
    assert control.paused is True
    assert control.reason == "verified_data_conflict"
    assert control.resume_allowed is True
    assert manager._pending_verified_fields[session_id] == "full_name"

    sent_types = [call.args[0].get("type") for call in websocket.send_json.await_args_list]
    assert "human.required" in sent_types
    human = next(call.args[0] for call in websocket.send_json.await_args_list if call.args[0].get("type") == "human.required")
    assert human["reason"] == "verified_data_conflict"
    assert human["control"] == "unlocked"


@pytest.mark.asyncio
async def test_verified_data_not_found_also_unlocks_without_exposing_value():
    manager = LiveBrowserManager()
    websocket = AsyncMock()
    session_id = "session-2"
    manager._channels[session_id] = websocket
    manager._channel_users[session_id] = "user-2"

    result = VerifiedDataResult(
        status=VerifiedDataStatus.NOT_FOUND,
        field_key="phone",
        value=None,
        message="phone value not found",
    )
    await manager.require_human_for_verified_data(session_id, "phone", result)

    control = manager._controls[session_id]
    assert control.control == "unlocked"
    assert control.mode == "human"
    human = next(call.args[0] for call in websocket.send_json.await_args_list if call.args[0].get("type") == "human.required")
    assert human["reason"] == "verified_data_not_found"
    assert "value" not in human
