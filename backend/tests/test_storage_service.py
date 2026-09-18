from unittest.mock import Mock

import pytest
from botocore.exceptions import ConnectTimeoutError

from app.storage_service import StorageServiceAdapter, StorageUploadError


def _row(node_id, provider, priority, credentials):
    return Mock(id=node_id, provider_name=provider, priority=priority, status="UP", credentials=credentials)


def _creds(endpoint, bucket):
    return {
        "endpoint_url": endpoint,
        "bucket_name": bucket,
        "access_key_id": "access-key",
        "secret_access_key": "secret-key",
        "region_name": "us-test-1",
        "public_base_url": f"{endpoint}/public",
    }


def test_primary_timeout_falls_back_to_ibm_and_marks_oracle_down():
    db = Mock()
    db.execute.return_value.fetchall.return_value = [
        _row("oracle-1", "oracle_cloud", 1, _creds("https://oracle.example", "oracle-bucket")),
        _row("ibm-2", "ibm_cos", 2, _creds("https://ibm.example", "ibm-bucket")),
    ]
    oracle = Mock()
    oracle.upload_fileobj.side_effect = ConnectTimeoutError(endpoint_url="https://oracle.example")
    ibm = Mock()
    client_factory = Mock(side_effect=[oracle, ibm])

    service = StorageServiceAdapter(db, client_factory=client_factory, failover_window_seconds=3.0, node_timeout_seconds=1.0)
    url = service.upload_bytes(object_key="users/u1/result.pdf", data=b"pdf", content_type="application/pdf")

    assert url == "https://ibm.example/public/users/u1/result.pdf"
    oracle.upload_fileobj.assert_called_once()
    ibm.upload_fileobj.assert_called_once()
    assert ibm.upload_fileobj.call_args.args[2] == "users/u1/result.pdf"
    assert ibm.upload_fileobj.call_args.kwargs["ExtraArgs"] == {"ContentType": "application/pdf"}
    assert db.commit.call_count == 1
    update_calls = [call for call in db.execute.call_args_list if len(call.args) > 1]
    assert any(call.args[1] == {"node_id": "oracle-1"} for call in update_calls)
    assert any("SET status = 'DOWN'" in call.args[0].text for call in update_calls)


def test_active_nodes_are_locked_and_ordered_by_priority():
    db = Mock()
    db.execute.return_value.fetchall.return_value = []

    assert StorageServiceAdapter(db)._lock_active_nodes() == []
    statement = db.execute.call_args.args[0].text
    assert "WHERE status = 'UP'" in statement
    assert "ORDER BY priority ASC" in statement
    assert "FOR UPDATE" in statement


def test_all_transient_failures_raise_and_mark_each_node_down():
    db = Mock()
    db.execute.return_value.fetchall.return_value = [
        _row("oracle-1", "oracle_cloud", 1, _creds("https://oracle.example", "oracle-bucket")),
        _row("ibm-2", "ibm_cos", 2, _creds("https://ibm.example", "ibm-bucket")),
    ]
    failing_client = Mock()
    failing_client.upload_fileobj.side_effect = ConnectTimeoutError(endpoint_url="https://timeout.example")

    with pytest.raises(StorageUploadError):
        StorageServiceAdapter(db, client_factory=Mock(return_value=failing_client)).upload_bytes(
            object_key="x.bin", data=b"x", content_type="application/octet-stream"
        )

    assert db.commit.call_count == 2
