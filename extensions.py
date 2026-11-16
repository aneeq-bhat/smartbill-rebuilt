from flask import Flask
from config import Config

def configure_app(app: Flask):
    app.config.from_object(Config)
    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY is missing. Set it in your .env file.")
