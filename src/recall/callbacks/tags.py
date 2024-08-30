"""Callbacks for the tag management tab."""

from dash import Input, Output, State, callback, ALL, ctx
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc

from recall.database.connection import db
from recall.database.models import Tag


@callback(
    Output('tag-collection', 'children'),
    Output('add-tag', 'disabled'),
    Input('tag-name', 'value'),
    Input('tag-update-signal', 'data'),
    State('selected-tag-id', 'data'),
)
def populate_tag_collection(tag_name, signal, selected_tag_id):
    """Populate the tag collection.

    The tag collection holds all tags in the database.
    The matching tags are highlighted.
    """
    matching_tags_ids = []
    full_match = False
    if tag_name:
        matching_tags = db.session.query(Tag).filter(Tag.name.ilike(f'%{tag_name}%')).all()
        matching_tags_ids = [tag.id for tag in matching_tags]
        full_match = any(tag.name == tag_name for tag in matching_tags)
    tags = db.session.query(Tag).order_by(Tag.name).all()
    tag_buttons = []
    # Disable the add button if the tag name is empty or tag_name already exists
    adding_disabled = not tag_name or full_match or selected_tag_id > -1
    for tag in tags:
        if tag.id in matching_tags_ids:
            if tag.id == selected_tag_id:
                color = 'primary'
            else:
                color = 'danger' if full_match else 'warning'
        else:
            color = 'secondary'
        button = dbc.Button(
            tag.name,
            id={'type': 'tag-button', 'index': tag.id},
            active=tag.id == selected_tag_id,
            color=color, outline=True, size='sm', class_name='mr-2 mb-2',
        )
        tag_buttons.append(button)
    return tag_buttons, adding_disabled


@callback(
    Output('tag-name', 'value'),
    Output('tag-description', 'value'),
    Output('selected-tag-id', 'data'),
    Output('save-tag', 'disabled'),
    Output('delete-tag', 'disabled'),
    State('selected-tag-id', 'data'),
    Input('tag-update-signal', 'data'),
    Input({'type': 'tag-button', 'index': ALL}, 'n_clicks'),
    State({'type': 'tag-button', 'index': ALL}, 'id'),
    prevent_initial_call=True
)
def tag_selected(selected_tag_id, signal, n_clicks, button_ids):
    """Update the tag form based on the selected tag."""
    if type(ctx.triggered_id) != str: # button event
        if any(n_clicks):
            # Find the index of the clicked button
            clicked_index = next(i for i, clicks in enumerate(n_clicks) if clicks)
            button_id = button_ids[clicked_index]
            tag_id = button_id['index']
            if tag_id == selected_tag_id:
                return '', '', -1, True, True
        else:
            # it's unclear why we would get here, but it happens
            raise PreventUpdate
    elif signal.get('status') == 'added':
        tag_id = signal.get('id')
    elif signal.get('status') == 'deleted':
        return '', '', -1, True, True
    else:
        raise PreventUpdate
    tag = db.session.query(Tag).get(tag_id)
    return tag.name, tag.description, tag_id, False, False


@callback(
    Output('add-tag', 'n_clicks'),
    Output('tag-update-signal', 'data', allow_duplicate=True),
    Input('add-tag', 'n_clicks'),
    State('tag-name', 'value'),
    State('tag-description', 'value'),
    prevent_initial_call=True
)
def add_tag(n_clicks, name, description):
    """Add a new tag to the database."""
    if not n_clicks:
        raise PreventUpdate
    if not name:
        return 0, {'status': 'empty'}
    tag = Tag(name=name, description=description)
    db.session.add(tag)
    db.session.commit()
    return 0, {'status': 'added', 'id': tag.id}


@callback(
    Output('save-tag', 'n_clicks'),
    Output('tag-update-signal', 'data', allow_duplicate=True),
    Input('save-tag', 'n_clicks'),
    State('tag-name', 'value'),
    State('tag-description', 'value'),
    State('selected-tag-id', 'data'),
    prevent_initial_call=True
)
def save_tag(n_clicks, name, description, tag_id):
    """Save changes to the selected tag."""
    if not n_clicks:
        raise PreventUpdate
    tag = db.session.query(Tag).get(tag_id)
    tag.name = name
    tag.description = description
    db.session.commit()
    return 0, {'status': 'updated'}


@callback(
    Output('delete-tag', 'n_clicks'),
    Output('tag-update-signal', 'data', allow_duplicate=True),
    Input('delete-tag', 'n_clicks'),
    State('selected-tag-id', 'data'),
    prevent_initial_call=True
)
def delete_tag(n_clicks, tag_id):
    """Delete the selected tag from the database."""
    if not n_clicks:
        raise PreventUpdate
    tag = db.session.query(Tag).get(tag_id)
    db.session.delete(tag)
    db.session.commit()
    return 0, {'status': 'deleted'}