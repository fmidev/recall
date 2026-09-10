"""Callbacks for the tag management tab."""

from dash import Input, Output, State, callback, ALL, ctx
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
from sqlalchemy.exc import IntegrityError

from recall.database.connection import db
from recall.database.models import Tag


@callback(
    Output("tag-collection", "children"),
    Output("add-tag", "disabled"),
    Input("tag-name", "value"),
    Input("tag-update-signal", "data"),
    State("selected-tag-id", "data"),
)
def populate_tag_collection(tag_name, signal, selected_tag_id):
    """Populate the tag collection.

    The tag collection holds all tags in the database.
    The matching tags are highlighted.
    """
    matching_tags_ids = []
    full_match = False
    if tag_name:
        matching_tags = (
            db.session.query(Tag).filter(Tag.name.ilike(f"%{tag_name}%")).all()
        )
        matching_tags_ids = [tag.id for tag in matching_tags]
        full_match = any(tag.name == tag_name for tag in matching_tags)
    tags = db.session.query(Tag).order_by(Tag.name).all()
    tag_buttons = []
    # Disable the add button if the tag name is empty or tag_name already exists
    adding_disabled = not tag_name or full_match or selected_tag_id > -1
    for tag in tags:
        if tag.id in matching_tags_ids:
            if tag.id == selected_tag_id:
                color = "primary"
            else:
                color = "danger" if full_match else "warning"
        else:
            color = "secondary"
        button = dbc.Button(
            tag.name,
            id={"type": "tag-button", "index": tag.id},
            active=tag.id == selected_tag_id,
            color=color,
            outline=True,
            size="sm",
            class_name="mr-2 mb-2",
        )
        tag_buttons.append(button)
    return tag_buttons, adding_disabled


@callback(
    Output("tag-name", "value"),
    Output("tag-description", "value"),
    Output("selected-tag-id", "data"),
    Output("save-tag", "disabled"),
    Output("delete-tag", "disabled"),
    State("selected-tag-id", "data"),
    Input("tag-update-signal", "data"),
    Input({"type": "tag-button", "index": ALL}, "n_clicks"),
    State({"type": "tag-button", "index": ALL}, "id"),
    prevent_initial_call=True,
)
def tag_selected(selected_tag_id, signal, n_clicks, button_ids):
    """Update the tag form based on the selected tag."""
    if isinstance(ctx.triggered_id, dict):
        if any(n_clicks):
            tag_id = ctx.triggered_id["index"]
            if tag_id == selected_tag_id:
                return "", "", -1, True, True
        else:
            # it's unclear why we would get here, but it happens
            raise PreventUpdate
    elif signal and signal.get("status") == "added":
        tag_id = signal.get("id")
    elif signal and signal.get("status") == "deleted":
        return "", "", -1, True, True
    else:
        raise PreventUpdate
    tag = db.session.get(Tag, tag_id)
    if tag is None:
        return "", "", -1, True, True
    return tag.name, tag.description, tag_id, False, False


@callback(
    Output("add-tag", "n_clicks"),
    Output("tag-update-signal", "data", allow_duplicate=True),
    Input("add-tag", "n_clicks"),
    State("tag-name", "value"),
    State("tag-description", "value"),
    prevent_initial_call=True,
)
def add_tag(n_clicks, name, description):
    """Add a new tag to the database."""
    if not n_clicks:
        raise PreventUpdate
    error = validate_tag_name(name)
    if error:
        return 0, {"status": "invalid", "message": error}
    tag = Tag(name=name.strip(), description=description)
    db.session.add(tag)
    return commit_tag(tag, "added")


@callback(
    Output("save-tag", "n_clicks"),
    Output("tag-update-signal", "data", allow_duplicate=True),
    Input("save-tag", "n_clicks"),
    State("tag-name", "value"),
    State("tag-description", "value"),
    State("selected-tag-id", "data"),
    prevent_initial_call=True,
)
def save_tag(n_clicks, name, description, tag_id):
    """Save changes to the selected tag."""
    if not n_clicks:
        raise PreventUpdate
    error = validate_tag_name(name)
    if error:
        return 0, {"status": "invalid", "message": error}
    tag = db.session.get(Tag, tag_id)
    if tag is None:
        return 0, {"status": "invalid", "message": "This tag no longer exists."}
    tag.name = name.strip()
    tag.description = description
    return commit_tag(tag, "updated")


@callback(
    Output("delete-tag", "n_clicks"),
    Output("tag-update-signal", "data", allow_duplicate=True),
    Input("confirm-delete-tag", "submit_n_clicks"),
    State("selected-tag-id", "data"),
    prevent_initial_call=True,
)
def delete_tag(n_clicks, tag_id):
    """Delete the selected tag from the database."""
    if not n_clicks:
        raise PreventUpdate
    tag = db.session.get(Tag, tag_id)
    if tag is None:
        return 0, {"status": "invalid", "message": "This tag no longer exists."}
    db.session.delete(tag)
    db.session.commit()
    return 0, {"status": "deleted"}


def validate_tag_name(name):
    if not name or not name.strip():
        return "Enter a tag name."
    if len(name.strip()) > 255:
        return "Tag names must be at most 255 characters."
    return None


def commit_tag(tag, status):
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        if getattr(exc.orig, "pgcode", None) == "23505":
            return 0, {
                "status": "invalid",
                "message": "A tag with this name already exists.",
            }
        raise
    return 0, {"status": status, "id": tag.id}


@callback(
    Output("tag-feedback", "children"),
    Output("tag-feedback", "color"),
    Output("tag-feedback", "is_open"),
    Input("tag-update-signal", "data"),
)
def tag_feedback(signal):
    if not signal:
        return "", "info", False
    if signal.get("status") == "invalid":
        return signal["message"], "danger", True
    return "Tag changes saved.", "success", True
