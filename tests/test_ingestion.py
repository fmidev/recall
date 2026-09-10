from datetime import datetime
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError
from rasterio.errors import CRSError
from terracotta.exceptions import InvalidDatabaseError

from recall.terracotta import ingest


TIME = datetime(2026, 9, 10, 10)


@pytest.fixture
def driver(monkeypatch):
    driver = Mock(key_names=ingest.KEYS)
    driver.get_datasets.return_value = {}
    monkeypatch.setattr(ingest, "get_driver", lambda: driver)
    monkeypatch.setattr(ingest, "_s3_client", Mock(return_value=Mock()))
    return driver


def test_existing_scan_uses_targeted_lookup_without_archive_access(driver):
    driver.get_datasets.return_value = {("202609101000", "fikor", "DBZH"): "path"}
    s3 = Mock()
    assert ingest.insert(TIME, "fikor", "DBZ-1", s3=s3) == "existing"
    driver.get_datasets.assert_called_once_with(
        {"timestamp": "202609101000", "radar": "fikor", "product": "DBZH"}
    )
    s3.head_object.assert_not_called()
    driver.insert.assert_not_called()


def test_s3_path_and_normalized_key(driver):
    s3 = Mock()
    assert ingest.insert(TIME, "fikor", "dbz-1", s3=s3) == "inserted"
    s3.head_object.assert_called_once_with(
        Bucket=ingest.S3_BUCKET,
        Key="2026/09/10/fikor/202609101000_fikor_DBZ-1.tif",
    )
    driver.insert.assert_called_once_with(
        ("202609101000", "fikor", "DBZH"),
        "s3://fmi-opendata-radar-geotiff/2026/09/10/fikor/202609101000_fikor_DBZ-1.tif",
    )


@pytest.mark.parametrize(
    "code,exception", [("404", ingest.MissingScanError), ("403", ClientError)]
)
def test_missing_and_forbidden_are_not_equivalent(driver, code, exception):
    s3 = Mock()
    s3.head_object.side_effect = ClientError({"Error": {"Code": code}}, "HeadObject")
    with pytest.raises(exception):
        ingest.insert(TIME, "fikor", "DBZH", s3=s3)
    driver.insert.assert_not_called()


def test_absent_primary_tries_legacy_product(driver, monkeypatch):
    insert = Mock(side_effect=[ingest.MissingScanError(), "inserted"])
    monkeypatch.setattr(ingest, "insert", insert)
    result = ingest.ingest_scans([TIME], "fikor")
    assert result.inserted == 1
    assert result.status == "ready"
    assert [call.args[2] for call in insert.call_args_list] == ["DBZH", "DBZ-1"]


def test_both_missing_are_reported(driver, monkeypatch):
    monkeypatch.setattr(ingest, "insert", Mock(side_effect=ingest.MissingScanError()))
    progress = Mock()
    result = ingest.ingest_scans([TIME], "fikor", progress)
    assert result.missing == 1
    assert result.inserted == result.failed == 0
    assert result.status == "partial"
    progress.assert_called_once_with((1, 1, "1/1"))


def test_corrupt_raster_is_reported_not_silently_accepted(driver, monkeypatch):
    insert = Mock(side_effect=CRSError("bad CRS"))
    monkeypatch.setattr(ingest, "insert", insert)
    result = ingest.ingest_scans([TIME], "fikor")
    assert result.failed == 1
    assert result.missing == result.inserted == 0
    assert result.status == "partial"
    assert "CRSError" in result.issues[0]
    insert.assert_called_once()


def test_unexpected_errors_propagate(driver, monkeypatch):
    monkeypatch.setattr(ingest, "insert", Mock(side_effect=RuntimeError("bug")))
    with pytest.raises(RuntimeError, match="bug"):
        ingest.ingest_scans([TIME], "fikor")


def test_wrong_database_keys_do_not_trigger_reinitialization(driver):
    driver.key_names = ("old", "keys")
    with pytest.raises(InvalidDatabaseError):
        ingest.ingest_scans([TIME], "fikor")
    driver.create.assert_not_called()


def test_mixed_results_count_scans_not_product_attempts(driver, monkeypatch):
    insert = Mock(
        side_effect=[
            "existing",
            "inserted",
            ingest.MissingScanError(),
            ingest.MissingScanError(),
            CRSError("bad CRS"),
        ]
    )
    monkeypatch.setattr(ingest, "insert", insert)
    result = ingest.ingest_scans([TIME] * 4, "fikor")
    assert (result.existing, result.inserted, result.missing, result.failed) == (
        1,
        1,
        1,
        1,
    )
