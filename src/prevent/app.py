from flask import Flask, request, jsonify, render_template
from prevent.models import session, Event
from prevent.downloader import download_single_radar_dbz
import datetime

app = Flask(__name__)


@app.route('/')
def main_view():
    return render_template('main_view.html')


@app.route('/events', methods=['GET'])
def get_events():
    events = session.query(Event).all()
    events_list = [
        {
            'event_id': event.event_id,
            'radar_id': event.radar_id,
            'start_time': event.start_time.isoformat(),
            'end_time': event.end_time.isoformat(),
            'description': event.description
        } for event in events
    ]
    return jsonify(events_list)


@app.route('/single_radar', methods=['GET'])
def single_radar():
    radar_name = request.args.get('radar')
    time_str = request.args.get('time')
    time = datetime.datetime.strptime(time_str, '%Y-%m-%dT%H:%M:%SZ')
    try:
        file_path = download_single_radar_dbz(radar_name, time)
        return jsonify({'message': 'Download successful', 'file_path': file_path}), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

if __name__ == '__main__':
    app.run(debug=True)