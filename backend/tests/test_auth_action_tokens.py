from app.auth import generate_one_time_token, hash_one_time_token


def test_one_time_tokens_are_random_and_only_hash_is_persisted():
    first = generate_one_time_token()
    second = generate_one_time_token()
    assert first != second
    assert hash_one_time_token(first) != first
    assert len(hash_one_time_token(first)) == 64
