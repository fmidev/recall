import datetime


def list_scan_timestamps(event):
    """List all radar scan timestamps in an event."""
    start_time = event.start_time
    end_time = event.end_time
    timestamps = [start_time + datetime.timedelta(minutes=5*i) for i in range(int((end_time - start_time).total_seconds() / 60 / 5))]
    return timestamps