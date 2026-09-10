from recall.domain import SCAN_INTERVAL, validate_event_interval


def list_scan_timestamps(event):
    """List expected scans in the event's half-open, five-minute UTC interval."""
    start_time, end_time = validate_event_interval(event.start_time, event.end_time)
    return [
        start_time + SCAN_INTERVAL * i
        for i in range((end_time - start_time) // SCAN_INTERVAL)
    ]
