from flask_wtf import FlaskForm
from wtforms import SelectField
from wtforms.validators import DataRequired

class EventSelectionForm(FlaskForm):
    event = SelectField('Select Event', validators=[DataRequired()], coerce=int)