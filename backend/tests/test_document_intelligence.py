from app.document_intelligence import _fields_from_text


def test_structured_fields_are_extracted_without_guessing():
    text = "Name: Rahul Kumar\nPAN: ABCDE1234F\nDOB: 12/08/2002\nEmail: rahul@example.com\nMobile: 9876543210"
    fields = {field.name: field for field in _fields_from_text(text)}
    assert fields["full_name"].value == "Rahul Kumar"
    assert fields["pan_number"].value == "ABCDE1234F"
    assert fields["date_of_birth"].value == "12/08/2002"
    assert fields["email"].value == "rahul@example.com"
    assert fields["phone"].value == "9876543210"


def test_no_field_is_created_for_missing_data():
    fields = _fields_from_text("This document contains no identifiable fields.")
    assert fields == []
