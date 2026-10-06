from unittest.mock import MagicMock, patch
import json
import gzip
from app.services.gstr1_run_store import save_gstr1_run, get_gstr1_run


def test_save_gstr1_run_with_r2():
    mock_sb = MagicMock()
    mock_sb.table.return_value.insert.return_value.execute.return_value.data = [{"id": "test-run-123"}]

    with patch("app.services.gstr1_run_store.is_r2_configured", return_value=True), \
         patch("app.services.gstr1_run_store.upload_bytes_to_r2") as mock_upload:
        saved = save_gstr1_run(mock_sb, client_gstin_id="test-cg-id", result={"summary": {"test": 1}})
        assert saved["id"] == "test-run-123"
        assert mock_upload.called


def test_get_gstr1_run_hydrates_r2():
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{
        "id": "test-run-123",
        "result_payload": {"_storage": "r2", "path": "gstr1-payloads/test.json.gz"}
    }]
    compressed = gzip.compress(json.dumps({"reconciled": True}).encode("utf-8"))
    with patch("app.services.gstr1_run_store.download_file_from_r2", return_value=compressed):
        run = get_gstr1_run(mock_sb, "test-run-123")
        assert run["result_payload"] == {"reconciled": True}
