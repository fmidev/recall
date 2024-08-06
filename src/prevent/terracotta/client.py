"""client for terracotta server"""

import os
import datetime


TC_URL = os.environ.get('TC_URL', 'http://localhost:8088')


def get_singleband_url(timestamp: datetime.datetime, radar_name: str, product: str, **kws):
    """Get the XYZ URL for a radar image."""
    product = product.upper()
    url = f'{TC_URL}/singleband/{timestamp.strftime("%Y%m%d%H%M")}/{radar_name}/{product}/'
    url += '{z}/{x}/{y}.png'
    # add query parameters
    if kws:
        url += '?'
        url += '&'.join([f'{k}={v}' for k, v in kws.items()])
    return url
