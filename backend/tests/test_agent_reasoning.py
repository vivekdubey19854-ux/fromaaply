from app.agent_reasoning import infer_field, plan_from_knowledge


def test_infer_supported_field():
    assert infer_field("fill applicant name") == "full_name"
    assert infer_field("enter PAN number") == "pan_number"
    assert infer_field("date of birth") == "date_of_birth"


def test_unknown_instruction_needs_clarification():
    result = plan_from_knowledge("do something", [])
    assert result["status"] == "needs_clarification"
    assert result["candidates"] == []


def test_sensitive_value_requires_approval():
    chunks = [{
        "source_type": "document_field",
        "source_id": "doc-1",
        "chunk_index": 0,
        "text": "Document PAN.pdf: pan_number: ABCDE1234F",
        "metadata": {},
    }]
    result = plan_from_knowledge("enter PAN number", chunks)
    assert result["status"] == "ready"
    assert result["requires_approval"] is True
    assert result["candidates"][0]["value"] == "ABCDE1234F"


def test_no_guessing_when_value_is_absent():
    chunks = [{"source_type": "profile", "source_id": "u1", "chunk_index": 0, "text": "Profile: full_name: Rahul", "metadata": {}}]
    result = plan_from_knowledge("enter PAN number", chunks)
    assert result["status"] == "needs_clarification"
    assert result["candidates"] == []
