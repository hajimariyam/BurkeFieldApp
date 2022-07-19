from __init__ import db

class User(db.Model):
    username = db.Column(db.String(80), primary_key=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)

class Log(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime(), nullable=False)
    user = db.Column(db.String(80), nullable=False)
    client = db.Column(db.String(150), nullable=False)
    project_number = db.Column(db.String(50), nullable=False)
    siteID = db.Column(db.Integer, default=0)
    photoID = db.Column(db.Integer, default=0)
    caption = db.Column(db.String(500))
    flagged = db.Column(db.Integer, default=0)
    pending = db.Column(db.Integer, default=0)
    immediate = db.Column(db.Integer, default=0)
    action = db.Column(db.String(6), nullable=False)

class PhotoItem(db.Model):
    photoID = db.Column(db.Integer, primary_key=True)
    siteID = db.Column(db.Integer)
    filename = db.Column(db.String(250))
    author = db.Column(db.String(50))
    latitude = db.Column(db.Integer, nullable=False)
    longitude = db.Column(db.Integer, nullable=False)
    time = db.Column(db.DateTime())
    comment = db.Column(db.String(500))
    orientation = db.Column(db.Integer, nullable=False)
    is_flagged = db.Column(db.Boolean, default=False)
    is_immediate = db.Column(db.Boolean, default=False)
    is_nonimmediate = db.Column(db.Boolean, default=False)

class SiteVisit(db.Model):
    sitevisitID = db.Column(db.Integer, primary_key=True)
    projID = db.Column(db.Integer, nullable=False)
    date = db.Column(db.DateTime(), nullable=False)
    notes = db.Column(db.String(250))

class Project(db.Model):
    projectID = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(250), nullable=False)
    client = db.Column(db.String(150), nullable=False)
    proj_number = db.Column(db.String(50), unique=True, nullable=False)
    location = db.Column(db.String(150), nullable=False)
    latitude = db.Column(db.Integer, nullable=False)
    longitude = db.Column(db.Integer, nullable=False)
