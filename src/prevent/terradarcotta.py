"""Ingest GeoTIFF files from S3 into a terracotta database."""

import os
import re
import datetime

import rasterio
from rasterio.session import AWSSession
from rasterio.errors import CRSError
from botocore import UNSIGNED
from botocore.config import Config
import boto3
import terracotta as tc
from terracotta.exceptions import InvalidDatabaseError

S3_BUCKET = 'fmi-opendata-radar-geotiff'
KEYS = ('timestamp', 'radar', 'product')
KEY_DESCRIPTIONS = {
    'timestamp': 'Measurement timestamp',
    'radar': 'Radar site',
    'product': 'Product type'
}
DB_URI = 'postgresql://preventuser:kukkakaalisinappi@localhost/terracotta'


def get_s3path(timestamp: datetime.datetime, radar: str, product: str):
    return f's3://{S3_BUCKET}/{timestamp.strftime("%Y/%m/%d")}/{radar}/{timestamp.strftime("%Y%m%d%H%M")}_{radar}_{product}.tif'


def insert(timestamp: datetime.datetime, radar: str, product: str):
    """Insert radar metadata into the terracotta database."""
    product = product.lower()
    #
    driver = tc.get_driver(DB_URI)
    config = Config(signature_version=UNSIGNED, region_name='eu-west-1')
    s3 = boto3.resource('s3', config=config)
    bucket = s3.Bucket(S3_BUCKET)
    # sanity 
    try:
        assert driver.key_names == KEYS
    except InvalidDatabaseError:
        driver.create(KEYS, key_descriptions=KEY_DESCRIPTIONS)
        assert driver.key_names == KEYS
    available_datasets = driver.get_datasets()
    #
    s3path = get_s3path(timestamp, radar, product)
    tstr = timestamp.strftime('%Y%m%d%H%M')
    keys = (tstr, radar, product)
    if keys in available_datasets:
        print('Skipping', s3path)
        return
    print('Ingesting', s3path)
    with driver.connect():
        with rasterio.Env(AWSSession(boto3.Session(), requester_pays=False), AWS_NO_SIGN_REQUEST='YES'):
            try:
                driver.insert(keys, s3path)
            except CRSError:
                print('CRSError, skipping')


def insert_event(event):
    """Insert all radar metadata for an event into the terracotta database."""
    start_time = event.start_time
    end_time = event.end_time
    times = [start_time + datetime.timedelta(minutes=5*i) for i in range(int((end_time-start_time).total_seconds()/60/5))]
    radar = event.radar
    radar_name = radar.name
    for time in times:
        insert(time, radar_name, 'dbzh')