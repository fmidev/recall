"""Ingest GeoTIFF files from S3 into a terracotta database."""

import os
import datetime

import rasterio
from rasterio.session import AWSSession
from rasterio.errors import CRSError
from botocore import UNSIGNED
from botocore.config import Config
import boto3
import terracotta as tc
from terracotta.exceptions import InvalidDatabaseError

from recall.database import list_scan_timestamps


S3_BUCKET = 'fmi-opendata-radar-geotiff'
KEYS = ('timestamp', 'radar', 'product')
KEY_DESCRIPTIONS = {
    'timestamp': 'Measurement timestamp',
    'radar': 'Radar site',
    'product': 'Product type'
}
DB_URI = os.environ.get('TC_DB_URI', 'postgresql://postgres:postgres@localhost:5432/terracotta')


def get_s3path(timestamp: datetime.datetime, radar: str, product: str):
    return f's3://{S3_BUCKET}/{timestamp.strftime("%Y/%m/%d")}/{radar}/{timestamp.strftime("%Y%m%d%H%M")}_{radar}_{product}.tif'


def insert(timestamp: datetime.datetime, radar: str, product: str):
    """Insert radar metadata into the terracotta database."""
    product = product.upper()
    #
    driver = tc.get_driver(DB_URI)
    config = Config(signature_version=UNSIGNED, region_name='eu-west-1')
    s3 = boto3.resource('s3', config=config)
    bucket = s3.Bucket(S3_BUCKET)
    # sanity 
    try:
        assert driver.key_names == KEYS
    except InvalidDatabaseError:
        driver.meta_store._initialize_database(KEYS, key_descriptions=KEY_DESCRIPTIONS)
        assert driver.key_names == KEYS
    available_datasets = driver.get_datasets()
    #
    s3path = get_s3path(timestamp, radar, product)
    tstr = timestamp.strftime('%Y%m%d%H%M')
    if 'DBZ' in product:
        product_key = 'DBZH'
    else:
        product_key = product
    keys = (tstr, radar, product_key)
    if keys in available_datasets:
        print('Skipping', s3path)
        return
    print('Ingesting', s3path)
    with driver.connect():
        with rasterio.Env(AWSSession(boto3.Session(), requester_pays=False), AWS_NO_SIGN_REQUEST='YES'):
            try:
                driver.insert(keys, s3path)
            except CRSError as e:
                print(e)
                print(f'Likely not a geotiff: {s3path}')


def dummy_progress_fun(*args, **kws):
    pass


def insert_event(event, set_progress=dummy_progress_fun):
    """Insert all radar metadata for an event into the terracotta database."""
    times = list_scan_timestamps(event)
    radar = event.radar
    radar_name = radar.name
    n_times = len(times)
    print(f'Inserting {n_times} timestamps for {radar_name}')
    for i, time in enumerate(times):
        for product in ('DBZH', 'DBZ-1'):
            try:
                insert(time, radar_name, product)
                break
            except Exception as e:
                print(e)
            finally:
                set_progress((i, n_times, f'{i}/{n_times}'))
