import os
import requests


DEFAULT_CACHE_DIR = '/tmp/prevent'
FMI_WMS_BASE_URL = 'https://openwms.fmi.fi/geoserver/wms'
SINGLE_RADAR_DBZ_LAYERS = {
    'fikor': 'Radar:korpo_dbzh',
    'fikes': 'Radar:kesalahti_dbzh',
    'fianj': 'Radar:anjalankoski_dbzh',
    'fikuo': 'Radar:kuopio_dbzh',
    'filuo': 'Radar:luosto_dbzh',
    'finur': 'Radar:nurmes_dbzh',
    'fipet': 'Radar:petajavesi_dbzh',
    'fikan': 'Radar:radar_kankaanpaa_dbzh-ppi_3067',
    'fiuta': 'Radar:utajarvi_dbzh',
    'fivim': 'Radar:vimpeli_dbzh',
    'fivih': 'Radar:vihti_ppi_ala_eureffin'
}

def fetch_single_radar_dbz(radar_name, time):
    if radar_name not in SINGLE_RADAR_DBZ_LAYERS:
        raise ValueError(f'Invalid radar name: {radar_name}')
    timestamp = time.strftime('%Y-%m-%dT%H:%M:%SZ')
    params = {
        'service': 'WMS',
        'version': '1.1.0',
        'request': 'GetMap',
        'layers': SINGLE_RADAR_DBZ_LAYERS[radar_name],
        'styles': 'raster',
        'format': 'image/geotiff',
        'transparent': 'true',
        'time': timestamp
    }
    response = requests.get(FMI_WMS_BASE_URL, params=params)
    response.raise_for_status()
    return response.content


def download_single_radar_dbz(radar_name, time, cache_dir=DEFAULT_CACHE_DIR):
    os.makedirs(cache_dir, exist_ok=True)
    filename = f'{radar_name}_{time.strftime("%Y%m%dT%H%M%S")}.tif'
    filepath = os.path.join(cache_dir, filename)
    print(f'Downloading radar data to {filepath}')
    if not os.path.exists(filepath):
        data = fetch_single_radar_dbz(radar_name, time)
        with open(filepath, 'wb') as f:
            f.write(data)
    return filepath


def download_event_data(event):
    start_time = event.start_time
    end_time = event.end_time
    # times every 5 minutes from start to end
    times = [start_time + datetime.timedelta(minutes=5*i) for i in range(int((end_time-start_time).total_seconds()/60/5))]
    radar = event.radar
    radar_name = radar.name
    files = []
    for time in times:
        files.append(download_single_radar_dbz(radar_name, time))