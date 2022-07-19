from flask import Flask
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
from os import path
import app_config

db = SQLAlchemy()
UPLOAD_FOLDER = 'static/uploads/'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
DB_NAME = "database.db"
app = Flask(__name__)
app.jinja_env.add_extension('jinja2.ext.loopcontrols')

def start_app():
    app.config['SECRET_KEY'] = 'CBBEL'
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_NAME}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = True
    app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
    app.config.from_object(app_config)

    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
    
    db.init_app(app)

    from views import views
    app.register_blueprint(views, url_prefix='/')
    from models import SiteVisit, PhotoItem, Project
    create_database(app)
    Session(app) 

    return app

# Create database if does not exist already
def create_database(app):
    if not path.exists(DB_NAME):
        db.create_all(app=app)
        print('Created Database!')