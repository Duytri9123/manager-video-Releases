"""Page routes Blueprint — serves the SPA for each tab."""
from flask import Blueprint
from core_app import _render_spa

bp = Blueprint("pages", __name__)


@bp.route("/")
def index():
    return _render_spa("user")


@bp.route("/config")
def page_config():
    return _render_spa("config")


@bp.route("/cookies")
def page_cookies():
    return _render_spa("cookies")


@bp.route("/download")
def page_download():
    return _render_spa("download")


@bp.route("/user")
def page_user():
    return _render_spa("user")


@bp.route("/transcribe")
def page_transcribe():
    return _render_spa("transcribe")


@bp.route("/history")
def page_history():
    return _render_spa("history")


@bp.route("/process")
def page_process():
    return _render_spa("process")


@bp.route("/publish")
def page_publish():
    return _render_spa("publish")
