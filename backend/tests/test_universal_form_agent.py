from app.form_mapping import infer_field
from app.universal_research import _url_ok

def test_universal_live_label_mapping_supports_private_and_government_style_labels():
    assert infer_field({'label':'Father Name','name':'father_name'}).field=='father_name'
    assert infer_field({'label':'District','name':'district'}).field=='district'
    assert infer_field({'label':'Photograph','name':'photo','type':'file'}).field=='photo'

def test_user_url_validation_rejects_unsafe_embedded_credentials():
    assert _url_ok('https://example.com/apply')
    assert not _url_ok('javascript:alert(1)')
    assert not _url_ok('https://user:pass@example.com/apply')
