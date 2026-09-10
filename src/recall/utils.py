from matplotlib.dates import ConciseDateFormatter, AutoDateLocator, date2num, MINUTELY


def timestamp_marks(timestamps):
    """Format the timestamp labels using ConciseDateFormatter and AutoDateLocator."""
    if not timestamps:
        return {}
    if len(timestamps) == 1:
        return {0: timestamps[0].strftime("%H:%M")}
    locator = AutoDateLocator()
    locator.intervald[MINUTELY] = [5, 10, 15, 30]
    formatter = ConciseDateFormatter(locator)
    ticks = locator.tick_values(timestamps[0], timestamps[-1])
    formatted_ticks = formatter.format_ticks(ticks)
    marks = {}
    for i, timestamp in enumerate(timestamps):
        ts = date2num(timestamp)
        if ts in ticks:
            marks[i] = formatted_ticks[ticks.tolist().index(ts)]
        else:
            marks[i] = ""
    return marks
