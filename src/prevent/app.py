import datetime

from flask import Flask, request, jsonify, render_template
from flask_bootstrap import Bootstrap5
from flask_wtf import CSRFProtect
from sqlalchemy.orm import scoped_session, sessionmaker
import folium

from prevent.models import Event, db
from prevent.data import sample_events
from prevent.forms import EventSelectionForm
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
    sample_events(db)


def get_coords(radar):
    lat = db.session.scalar(radar.location.ST_Y())
    lon = db.session.scalar(radar.location.ST_X())
    return lat, lon


@app.route('/', methods=['GET', 'POST'])
def main_view():
    # Create a map centered at Finland
    coords = (61.9241, 25.7482)
    zoom = 6
    form = EventSelectionForm()
    # Optionally, add markers or layers
    events = db.session.query(Event).all()
    form.event.choices = [(event.id, event.description) for event in events]
    event = None
    if form.validate_on_submit():
        event_id = form.event.data
        event = db.session.query(Event).get(event_id)
        # set the map center to the radar location
        coords = get_coords(event.radar)
        zoom = 9
    folium_map = folium.Map(location=coords, zoom_start=zoom)
    # Render the map to HTML
    map_html = folium_map._repr_html_()
    return render_template('event_view.html', form=form, map_html=map_html, event=event)


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