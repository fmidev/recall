"""Register public radar GeoTIFFs without hiding unavailable or failed scans."""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime

import boto3
import rasterio
import terracotta as tc
from botocore import UNSIGNED
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from rasterio.errors import CRSError, RasterioError
from sqlalchemy.exc import SQLAlchemyError

from recall.database import list_scan_timestamps


logger = logging.getLogger(__name__)
S3_BUCKET = "fmi-opendata-radar-geotiff"
KEYS = ("timestamp", "radar", "product")
KEY_DESCRIPTIONS = {
    "timestamp": "Measurement timestamp",
    "radar": "Radar site",
    "product": "Product type",
}
DB_URI = os.environ.get("TC_DB_URI", "postgresql://localhost:5432/terracotta")


class MissingScanError(Exception):
    """The requested product is absent from the archive."""


@dataclass
class IngestionResult:
    inserted: int = 0
    existing: int = 0
    missing: int = 0
    failed: int = 0
    issues: list = field(default_factory=list)

    @property
    def status(self):
        return "partial" if self.missing or self.failed else "ready"


def get_driver():
    """Use Terracotta's cached public driver; initialization is an explicit CLI step."""
    return tc.get_driver(DB_URI)


def get_s3path(timestamp: datetime, radar: str, product: str):
    return (
        f"s3://{S3_BUCKET}/{timestamp:%Y/%m/%d}/{radar}/"
        f"{timestamp:%Y%m%d%H%M}_{radar}_{product.upper()}.tif"
    )


def insert(timestamp, radar, product, *, driver=None, s3=None):
    """Return inserted/existing, or raise a specific archive/driver error."""
    driver = driver if driver is not None else get_driver()
    product = product.upper()
    product_key = "DBZH" if product in ("DBZH", "DBZ-1") else product
    keys = (timestamp.strftime("%Y%m%d%H%M"), radar, product_key)
    if driver.get_datasets(dict(zip(KEYS, keys))):
        return "existing"
    s3 = s3 if s3 is not None else _s3_client()
    s3path = get_s3path(timestamp, radar, product)
    key = s3path[len(f"s3://{S3_BUCKET}/"):]
    try:
        s3.head_object(Bucket=S3_BUCKET, Key=key)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            raise MissingScanError(s3path) from exc
        raise
    with rasterio.Env(AWS_NO_SIGN_REQUEST="YES"):
        driver.insert(keys, s3path)
    logger.info("Registered radar scan %s", s3path)
    return "inserted"


def _s3_client():
    return boto3.client(
        "s3",
        config=Config(
            signature_version=UNSIGNED,
            retries={"mode": "standard", "max_attempts": 3},
            connect_timeout=10,
            read_timeout=30,
        ),
    )


def ingest_scans(timestamps, radar_name, set_progress=None):
    """Try legacy reflectivity only for an absent primary product; report every scan."""
    driver = get_driver()
    # Fail once, clearly, for incompatible/uninitialized metadata databases.
    if tuple(driver.key_names) != KEYS:
        raise tc.exceptions.InvalidDatabaseError("Unexpected Terracotta dataset keys.")
    s3 = _s3_client()
    result = IngestionResult()
    for i, timestamp in enumerate(timestamps):
        try:
            for product in ("DBZH", "DBZ-1"):
                try:
                    outcome = insert(
                        timestamp, radar_name, product, driver=driver, s3=s3
                    )
                    break
                except MissingScanError:
                    if product == "DBZ-1":
                        raise
            if outcome == "inserted":
                result.inserted += 1
            else:
                result.existing += 1
        except MissingScanError:
            result.missing += 1
            result.issues.append(f"{timestamp:%Y-%m-%d %H:%M} UTC: scan unavailable")
            logger.warning("Missing scan for %s at %s", radar_name, timestamp)
        except (BotoCoreError, ClientError, CRSError, RasterioError, SQLAlchemyError) as exc:
            result.failed += 1
            result.issues.append(
                f"{timestamp:%Y-%m-%d %H:%M} UTC: {type(exc).__name__}"
            )
            logger.exception("Failed scan for %s at %s", radar_name, timestamp)
        if set_progress is not None:
            set_progress((i + 1, len(timestamps), f"{i + 1}/{len(timestamps)}"))
    return result


def insert_event(event, set_progress=None):
    return ingest_scans(list_scan_timestamps(event), event.radar.name, set_progress)
