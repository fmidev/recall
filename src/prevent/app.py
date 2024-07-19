import datetime

from flask import Flask, request, jsonify, render_template, g
from flask_bootstrap import Bootstrap5
from flask_wtf import CSRFProtect
from sqlalchemy.orm import scoped_session, sessionmaker
import folium

from prevent.models import Event, db
from prevent.downloader import download_single_radar_dbz


app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = 'postgresql://preventuser:kukkakaalisinappi@localhost/preventdb'
db.init_app(app)
app.secret_key = 'aijvnianwr'
bootstrap = Bootstrap5(app)
csrf = CSRFProtect(app)

# Create the database tables
with app.app_context():
    db.create_all()

# Create a scoped session
Session = scoped_session(sessionmaker(bind=engine))


@app.before_request
def before_request():
    # Attach a session to the current context before each request
    g.session = Session()


@app.teardown_appcontext
def teardown_appcontext(exception=None):
    # Remove the session at the end of each request
    Session.remove()


@app.route('/events', methods=['GET'])
def get_events():
    try:
        events = g.session.query(Event).all()
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
    except Exception as e:
        # Rollback in case of an error
        g.session.rollback()
        # Log the error or handle it as needed
        print(f"Error fetching events: {e}")
        return jsonify({"error": "Error fetching events"}), 500


@app.route('/')
def main_view():
    # Create a map centered at Finland
    start_coords = (61.9241, 25.7482)
    folium_map = folium.Map(location=start_coords, zoom_start=8)

    # Optionally, add markers or layers

    # Render the map to HTML
    map_html = folium_map._repr_html_()

    events = g.session.query(Event).all()

    return render_template('main_view.html', events=events, map_html=map_html)


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