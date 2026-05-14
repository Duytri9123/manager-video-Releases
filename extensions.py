"""Flask app factory — creates the app and registers all blueprints."""
from core_app import app, socketio


def create_app():
    """Register all blueprints and SocketIO handlers, return the app."""
    from routes.pages import bp as pages_bp
    from routes.queue import bp as queue_bp
    from routes.user import bp as user_bp
    from routes.download import bp as download_bp, register_socketio_handlers
    from routes.translate import bp as translate_bp
    from routes.tts import bp as tts_bp
    from routes.transcribe import bp as transcribe_bp
    from routes.process import bp as process_bp
    from routes.youtube import bp as youtube_bp
    from routes.config import bp as config_bp
    from routes.content import bp as content_bp
    from routes.facebook import bp as facebook_bp
    from routes.accounts import bp as accounts_bp
    from routes.tiktok import bp as tiktok_bp

    app.register_blueprint(pages_bp)
    app.register_blueprint(queue_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(download_bp)
    app.register_blueprint(translate_bp)
    app.register_blueprint(tts_bp)
    app.register_blueprint(transcribe_bp)
    app.register_blueprint(process_bp)
    app.register_blueprint(youtube_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(content_bp)
    app.register_blueprint(facebook_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(tiktok_bp)

    # Register SocketIO event handlers
    register_socketio_handlers()

    return app
