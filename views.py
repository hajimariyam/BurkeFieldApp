from io import BytesIO
from flask import Blueprint, render_template, url_for, request, redirect, flash, session, send_file
from flask.helpers import send_from_directory
from werkzeug.utils import secure_filename
from __init__ import db, ALLOWED_EXTENSIONS, app
import app_config
from datetime import datetime
from models import Project, SiteVisit, PhotoItem, User, Log
from flask import jsonify, json
from sqlalchemy import func
from zipfile import ZipFile
import os, io, shutil, csv
import requests, msal
from PIL import Image

views = Blueprint('views', __name__)
api_key = 'qlrRiPNTPWGYLnSG9qJmWGtSay-QVgiCqlNUyBoF_aY'

# Convert query of all projects to list object that can be jsonified
def convert_to_list(projects):
    converted_list = []
    for project in projects:
        dict = {
            "projectID": project.projectID,
            "name": project.name,
            "client": project.client,
            "proj_number": project.proj_number,
            "location": project.location,
            "latitude": project.latitude,
            "longitude": project.longitude
        }
        converted_list.append(dict)
    return converted_list


@views.route("/", methods=['GET', 'POST'])
def index():
    if not session.get("user"):
        return redirect(url_for("views.login"))
    if request.method == 'POST':
        projID = request.form['projectID']
        return redirect(url_for('views.view_all_site_visits', projID=projID))
    all_projects = Project.query.all()
    allprojs = convert_to_list(all_projects)
    projects = db.session.query(Project, Log.timestamp).join(Log, Log.project_number == Project.proj_number).filter(Log.user==session["user"].get("name"), Log.action=='READ').order_by(Log.timestamp.desc()).all()
    graphcall()
    # Remove duplicate projects from recent projects list
    while (True):
        if (remove_dup_projects(projects) == False):
            break
    return render_template('home.html',user=session["user"],projects=projects,allprojs=json.dumps(allprojs),deleted_project=None)


@views.route("/login")
def login():
    # Technically we could use empty list [] as scopes to do just sign in,
    # here we choose to also collect end user consent upfront
    session["flow"] = _build_auth_code_flow(scopes=app_config.SCOPE)
    return render_template("login.html", auth_url=session["flow"]["auth_uri"], version=msal.__version__)


@views.route(app_config.REDIRECT_PATH)  # Its absolute URL must match your app's redirect_uri set in AAD
def authorized():
    try:
        cache = _load_cache()
        result = _build_msal_app(cache=cache).acquire_token_by_auth_code_flow(
            session.get("flow", {}), request.args)
        if "error" in result:
            return render_template("auth_error.html", result=result)
        session["user"] = result.get("id_token_claims")
        _save_cache(cache)
    except ValueError:  # Usually caused by CSRF
        pass  # Simply ignore them
    return redirect(url_for("views.index"))


# ERROR PAGES
@views.route('/error-401')
def error_401():
    return render_template ('error_401.html')


@views.route('/error-404')
def error_404():
    return render_template ('error_404.html')


# Logout current user
@views.route("/logout")
def logout():
    if not session.get("user"):
        return redirect(url_for("views.error_401"))
    session.clear()  # Wipe out user and its token cache from session
    session.pop("user", None) #might have to move this to AFTER user clicks which acct to log out of
    return redirect(url_for("views.index"))
    # Below: logs out of microsoft account on device and requires to rewrite password
    '''
    return redirect(  # Also logout from your tenant's web session
        app_config.AUTHORITY + "/oauth2/v2.0/logout" +
        "?post_logout_redirect_uri=" + url_for("views.index", _external=True)y)
    '''


# Request graph API from microsoft and add new users to db
def graphcall():
    token = _get_token_from_cache(app_config.SCOPE)
    if not token:
        return redirect(url_for("views.login"))
    graph_data = requests.get(  # Use token to call downstream service
        app_config.ENDPOINT,
        headers={'Authorization': 'Bearer ' + token['access_token']},
        ).json()
    email = graph_data['mail']
    username = graph_data['displayName']
    existing_user = User.query.filter_by(username=username).first()
    if existing_user:
        return
    new_user = User(email=email,username=username)
    db.session.add(new_user)
    db.session.commit()


def _load_cache():
    cache = msal.SerializableTokenCache()
    if session.get("token_cache"):
        cache.deserialize(session["token_cache"])
    return cache


def _save_cache(cache):
    if cache.has_state_changed:
        session["token_cache"] = cache.serialize()


def _build_msal_app(cache=None, authority=None):
    return msal.ConfidentialClientApplication(
        app_config.CLIENT_ID, authority=authority or app_config.AUTHORITY,
        client_credential=app_config.CLIENT_SECRET, token_cache=cache)


def _build_auth_code_flow(authority=None, scopes=None):
    return _build_msal_app(authority=authority).initiate_auth_code_flow(
        scopes or [],
        redirect_uri=url_for("views.authorized", _external=True))


def _get_token_from_cache(scope=None):
    cache = _load_cache()  # This web app maintains one cache per session
    cca = _build_msal_app(cache=cache)
    accounts = cca.get_accounts()
    if accounts:  # So all account(s) belong to the current signed-in user
        result = cca.acquire_token_silent(scope, account=accounts[0])
        _save_cache(cache)
        return result

app.jinja_env.globals.update(_build_auth_code_flow=_build_auth_code_flow) 


# Log changes/updates to projects
def log_crud_project(project_number, action):
    timestamp = datetime.now()
    user = session["user"].get("name")
    client = Project.query.filter_by(proj_number=project_number).first().client

    # update 'read' log if already exists
    if action == 'READ':
        existing_read = Log.query.filter(Log.user == user).filter(Log.action == 'READ').filter(Log.project_number == project_number).first()
        if existing_read:
            existing_read.timestamp = timestamp
            db.session.commit()
            return

    # log new read, create, update, delete action for project
    new_log = Log(timestamp=timestamp,user=user,client=client,project_number=project_number,action=action)
    db.session.add(new_log)
    db.session.commit()

    # log a new 'read' query for each new project that is created
    if action == 'CREATE':
        new_log = Log(timestamp=timestamp,user=user,client=client,project_number=project_number,action='READ')
        db.session.add(new_log)
        db.session.commit()


# Log changes/updates to site visits
def log_crud_sitevisit(siteID, action):
    timestamp = datetime.now()
    user = session["user"].get("name")
    pid = SiteVisit.query.filter_by(sitevisitID=siteID).first().projID
    project_number = Project.query.filter_by(projectID=pid).first().proj_number
    client = Project.query.filter_by(proj_number=project_number).first().client

    # log create, update, delete action for site visit
    new_log = Log(timestamp=timestamp,user=user,client=client,project_number=project_number,siteID=siteID,action=action)
    db.session.add(new_log)
    db.session.commit()


# Log changes/updates to photo items
def log_crud_photoitem(photoID, action):
    timestamp = datetime.now()
    user = session["user"].get("name")
    siteID = PhotoItem.query.filter_by(photoID=photoID).first().siteID
    pid = SiteVisit.query.filter_by(sitevisitID=siteID).first().projID
    project_number = Project.query.filter_by(projectID=pid).first().proj_number
    client = Project.query.filter_by(proj_number=project_number).first().client
    photo = PhotoItem.query.filter_by(photoID=photoID).first()
    caption = photo.comment

    # log create, update, delete action for photo item
    if photo.is_flagged == True:
        new_log = Log(timestamp=timestamp,user=user,client=client,project_number=project_number,siteID=siteID,photoID=photoID,flagged=True,caption=caption,action=action)
    elif photo.is_immediate == True:
        new_log = Log(timestamp=timestamp,user=user,client=client,project_number=project_number,siteID=siteID,photoID=photoID,immediate=True,caption=caption,action=action)
    elif photo.is_nonimmediate == True:
        new_log = Log(timestamp=timestamp,user=user,client=client,project_number=project_number,siteID=siteID,photoID=photoID,pending=True,caption=caption,action=action)
    else:
        new_log = Log(timestamp=timestamp,user=user,client=client,project_number=project_number,siteID=siteID,photoID=photoID,caption=caption,action=action)
    db.session.add(new_log)
    db.session.commit()


# Remove duplicate projects and return true if duplicate found
def remove_dup_projects(projects):
    project_set = set()
    for project in projects:
        if project[0] in project_set:
            projects.remove(project)
            return True
        else:
            project_set.add(project[0])
    return False


# Return home screen with list of 5 most recent projects
@views.route('/home', methods=['GET', 'POST'])
def home():
    if not session.get("user"):
        return redirect(url_for("views.error_401"))# get latitude and longitude coordinates of project location
    if request.method == 'POST':
        projID = request.form['projectID']
        return redirect(url_for('views.view_all_site_visits', projID=projID))
    allprojects = Project.query.all()
    allprojs = convert_to_list(allprojects)
    projects = db.session.query(Project, Log.timestamp).join(Log, Log.project_number == Project.proj_number).filter(Log.user==session["user"].get("name"), Log.action=='READ').order_by(Log.timestamp.desc()).all()
    # Remove duplicate projects from recent projects list
    while (True):
        if (remove_dup_projects(projects) == False):
            break
    return render_template('home.html',allprojs=json.dumps(allprojs),projects=projects,user=session["user"],deleted_project=None)


# CLIENTS PAGE
@views.route('/view-clients/<sortby>', methods=['GET','POST'])
def view_clients(sortby="az"):
    if not session.get("user"):
        return redirect(url_for("views.error_401"))

    # alphabetical order (default)
    if sortby == "az":
        # func.lower is to ensure clients with uppercase letters are not sorted incorrectly due to ascii
        clients = Project.query.with_entities(Project.client).order_by(func.lower(Project.client)).distinct().all()

    # reverse alphabetical order
    if sortby == "za":
        clients = Project.query.with_entities(Project.client).order_by(func.lower(Project.client).desc()).distinct().all()

    # order by date of last accessed timestamp
    if sortby == "la":
        dup_clients = db.session.query(Project, Log.timestamp).join(Log, Log.project_number==Project.proj_number).filter(Log.action=='READ', Log.user==session["user"].get("name")).order_by(func.lower(Log.timestamp).desc()).all()

        def client_exists(client_name, clients):
            index = 0
            for row in clients:
                if (row[0].client == client_name):
                    return index
                index+1
            return -1

        clients = []
        for client in dup_clients:
            index = client_exists(client[0].client, clients)
            if index == -1:
                clients.append(client)
            else:
                if (client[1] > clients[index][1]):
                    clients[index][1] = client[1]

    # search clients
    search = ""
    if request.method == 'POST':
        search_value = request.form['search_string']
        search = "%{}%".format(search_value)
        clients = Project.query.with_entities(Project.client).filter(Project.client.like(search)).order_by(func.lower(Project.client)).distinct().all()
        
    return render_template('view_clients.html', clients=clients, user=session["user"], sortby=sortby, search=search)       


# PROJECTS PAGE
@views.route('/view-projects/<sortby>/<client>/', methods=['GET','POST'])
def view_projects(client, sortby="asc"):
    if not session.get("user"):
        return redirect(url_for("views.error_401"))
    if not client:
        return redirect(url_for("views.error_404"))

    # ascending order (default)
    if sortby == "asc":
        projects = Project.query.filter_by(client=client).order_by(Project.proj_number).all()
        
    # descending order
    if sortby == "desc":
        projects = Project.query.filter_by(client=client).order_by(Project.proj_number.desc()).all()
        
    # order by date of last accessed
    if sortby == "la":
        projects = db.session.query(Project, Log.timestamp).join(Log, Log.project_number==Project.proj_number).filter(Project.client==client, Log.action=='READ', Log.user==session["user"].get("name")).order_by(Log.timestamp.desc()).all()

    # search projects
    search = ""
    if request.method == 'POST':
        search_value = request.form['search_string']
        search = "%{}%".format(search_value)
        projects = Project.query.filter(Project.client==client, Project.proj_number.like(search)).order_by(Project.proj_number).all()
    
    prefixes = ["Village of ", "City of ", "Town of ", "County of "]

    return render_template('view_projects.html', projects=projects, client=client, user=session["user"], sortby=sortby, prefixes=prefixes, search=search)


# Return create project page
@views.route('/create-project')
def create_project():
    if not session.get("user"):
        return redirect(url_for("views.error_401"))
    return render_template('create_project.html', user=session["user"])


# Create new project and return to home page
@views.route('/new-project', methods=['POST'])
def new_project():
    if not session.get("user"):
        return redirect(url_for("views.error_401"))
    if request.method == 'POST':
        name = request.form['name']
        client = request.form['client']
        proj_number = request.form['proj_number']
        location = request.form['location']
        existing_proj_num = Project.query.filter_by(proj_number=proj_number).first()
        if existing_proj_num:
            flash('Project number already exists.', category='error')
            return redirect(url_for('views.create_project'))

        # get latitude and longitude coordinates of project location
        URL = "https://geocode.search.hereapi.com/v1/geocode"
        PARAMS = {'apikey':api_key,'q':location} 
        r = requests.get(url = URL, params = PARAMS) 
        data = r.json()
        latitude = data['items'][0]['position']['lat']
        longitude = data['items'][0]['position']['lng']

        new_project = Project(name=name,client=client,proj_number=proj_number,location=location,latitude=latitude,longitude=longitude)
        db.session.add(new_project)
        db.session.commit()
        # Log create project for current user
        log_crud_project(proj_number, action='CREATE')
        flash('Success! New project has been created.', category='success')
        return redirect(url_for('views.view_all_site_visits', projID = new_project.projectID))


# Return edit project page with projectID
@views.route('/edit-project/<projID>/', methods=['GET'])
def edit_project(projID):
    if not session.get("user"):
        return redirect(url_for("views.error_401"))
    proj = Project.query.filter_by(projectID=projID).first()
    if not proj:
        return redirect(url_for("views.error_404"))
    return render_template('edit_project.html',proj=proj,user=session["user"],apikey=api_key)


# Update project with db and return to list view of all site visits for this project
@views.route('/update-project', methods=['GET', 'POST'])
def update_project():
    if not session.get("user"):
        return redirect(url_for("views.error_401"))
    if request.method == 'POST':
        data = Project.query.get(request.form.get('projID'))
        if not data:
            return redirect(url_for("views.error_404"))
        columns = ['name', 'client', 'proj_number', 'location']
        for x in columns:
            # update db column if text field was edited
            if getattr(data, x) != request.form[x]:
                setattr(data, x, request.form[x])
                # log only once per edit regardless of number of fields updated
                if columns.index(x) == 0:
                    log_crud_project(data.proj_number, action='UPDATE')
        # get latitude and longitude coordinates of project location
        URL = "https://geocode.search.hereapi.com/v1/geocode"
        PARAMS = {'apikey':api_key,'q':data.location} 
        r = requests.get(url = URL, params = PARAMS) 
        mapdata = r.json()
        latitude = mapdata['items'][0]['position']['lat']
        longitude = mapdata['items'][0]['position']['lng']
        data.latitude = latitude
        data.longitude = longitude
        db.session.commit()
        flash("Success! Project has been updated.")
        return redirect(url_for('views.view_all_site_visits', projID=data.projectID))
    

# Delete project and return to home page
@views.route('/delete-project/<id>/', methods=['GET', 'POST'])
def delete_project(id):
    if not session.get("user"):
        return redirect(url_for("views.error_401"))
    project = Project.query.get(id)
    allphotos = []
    if not project:
        return redirect(url_for("views.error_404"))
    project_author = Log.query.filter(Log.action=='CREATE', Log.project_number==project.proj_number, Log.siteID==0, Log.photoID==0).first().user
    if project_author == session["user"].get("name"):
        sitevisits = SiteVisit.query.filter_by(projID=id).order_by(SiteVisit.date.desc()).all()
        if not sitevisits:
            pass
        else:
            for sitevisit in sitevisits:
                photos = PhotoItem.query.filter_by(siteID=sitevisit.sitevisitID).all()
                if not photos:
                    pass
                else:
                    for photo in photos:
                        allphotos.append(photo)
                        log_crud_photoitem(photo.photoID, action='DELETE')
                        db.session.delete(photo)
                        db.session.commit()
                        fileStringDel = (photo.filename).split('.jpg')
                        # temporarily store photos in temp folder
                        source = 'static/uploads/' + photo.filename
                        destination = 'static/temp'
                        dest = shutil.move(source, destination)
                        source2 = 'static/uploads/' + fileStringDel[0] + '_resized.jpg'
                        dest2 = shutil.move(source2, destination)
                log_crud_sitevisit(sitevisit.sitevisitID, action='DELETE')
                db.session.delete(sitevisit)
        log_crud_project(project.proj_number, action='DELETE')
        db.session.delete(project)
        db.session.commit()
    else:
        flash("You're not authorized to delete this project.", category='error')
        return redirect(url_for('views.home'))
    allprojects = Project.query.all()
    allprojs = convert_to_list(allprojects)
    
    # Save deleted project data into session data
    session['deleted_project'] = project
    session['deleted_visits'] = sitevisits
    session['deleted_photos'] = allphotos
    projects = db.session.query(Project, Log.timestamp).join(Log, Log.project_number == Project.proj_number).filter(Log.user==session["user"].get("name"), Log.action=='READ').order_by(Log.timestamp.desc()).all()
    # Remove duplicate projects from recent projects list
    while (True):
        if (remove_dup_projects(projects) == False):
            break
    return render_template('home.html', deleted_project=project,allprojs=json.dumps(allprojs),projects=projects,user=session["user"])


# Recover deleted project and return home
@views.route('/undo-delete-project/', methods=['GET', 'POST'])
def undo_delete_project():
    if not session.get("user"):
        return redirect(url_for("views.error_401"))
    # Add project back to db
    proj = session['deleted_project']
    new_project = Project(projectID=proj.projectID,name=proj.name,client=proj.client,proj_number=proj.proj_number,location=proj.location,latitude=proj.latitude,longitude=proj.longitude)
    db.session.add(new_project)
    db.session.commit()
    # Add site visits back to db
    visits = session['deleted_visits']
    for visit in visits:
        new_visit = SiteVisit(sitevisitID=visit.sitevisitID,projID=visit.projID,date=visit.date,notes=visit.notes)
        db.session.add(new_visit)
        db.session.commit()
    # Add photos back to db 
    photos = session['deleted_photos']
    for photo in photos:
        new_photo_item = PhotoItem(photoID=photo.photoID,time=photo.time,comment=photo.comment,filename=photo.filename,siteID=photo.siteID, orientation=photo.orientation,
            author=photo.author,latitude=photo.latitude,longitude=photo.longitude,is_flagged=photo.is_flagged, is_immediate=photo.is_immediate, is_nonimmediate=photo.is_nonimmediate)
        db.session.add(new_photo_item)
        db.session.commit()
        # Retrive photo from temp folder
        fileStringDel = (photo.filename).split('.jpg')
        source = 'static/temp/' + photo.filename
        destination = 'static/uploads'
        dest = shutil.move(source, destination)
        source2 = 'static/temp/' + fileStringDel[0] + '_resized.jpg'
        dest2 = shutil.move(source2, destination)

    return redirect(url_for('views.home'))


# Create new site visit
def new_site_visit(projID, date):
    if not projID:
        return redirect(url_for("views.error_404"))
    new_visit = SiteVisit(projID=projID,date=date)
    db.session.add(new_visit)
    db.session.commit()
    return new_visit.sitevisitID


# Add photo item to db and return to upload photo page
@views.route('/create-photo-item/<file>', methods=['GET', 'POST'])
def create_photo_item(file):
    if not session.get("user"):
        return redirect(url_for("views.error_401"))
    if request.method == 'POST':
        projID = request.form['projID']
        project = Project.query.get(projID)
        if not project:
            os.remove('static/uploads/' + file)
            return redirect(url_for("views.error_404"))
        # Obtain all information from add photo page
        comment = request.form['comment']
        action = request.form['action']
        siteID = request.form['siteID']
        latitude = request.form['latitude']
        longitude = request.form['longitude']
        orientation = request.form['orientation']
        time = datetime.now()
        filename = file
        author = session["user"].get("name")
        # Add visit. Create a new site visit for today if does not already exist.
        # Else, add photo to the selected site visit
        if siteID == '-1':
            date = time
            existing_site_visit = SiteVisit.query.filter(SiteVisit.projID==projID, SiteVisit.date.contains(date.strftime("%Y-%m-%d"))).first()
            if existing_site_visit:
                siteID = existing_site_visit.sitevisitID
            else:
                siteID = new_site_visit(projID, date)
                log_crud_sitevisit(siteID,action='CREATE')
        # Create new photo item and link to sitevisitID
        if action == 'is_flagged':
            new_photo_item = PhotoItem(time=time,comment=comment,filename=filename,siteID=siteID,
            author=author,latitude=latitude,longitude=longitude,is_flagged=True,orientation=orientation)
        elif action == 'is_immediate':
            new_photo_item = PhotoItem(time=time,comment=comment,filename=filename,siteID=siteID,
            author=author,latitude=latitude,longitude=longitude,is_immediate=True,orientation=orientation)
        elif action == 'is_nonimmediate':
            new_photo_item = PhotoItem(time=time,comment=comment,filename=filename,siteID=siteID,
            author=author,latitude=latitude,longitude=longitude,is_nonimmediate=True,orientation=orientation)
        else:
            new_photo_item = PhotoItem(time=time,comment=comment,filename=filename,siteID=siteID,
            author=author,latitude=latitude,longitude=longitude,orientation=orientation)
        db.session.add(new_photo_item)
        sitevisit = SiteVisit.query.get(siteID)
        if not sitevisit:
            db.session.delete(new_photo_item)
            os.remove('static/uploads/' + file)
            return redirect(url_for("views.error_404"))
        photoID = PhotoItem.query.filter(PhotoItem.filename==new_photo_item.filename).first().photoID
        log_crud_photoitem(photoID, action='CREATE')
        db.session.commit()
        
    return redirect(url_for('views.view_site_visit', siteID=siteID, sortby='desc', view=filename)) 


# Remove filename from upload folder and redirect to view site visit or view all site visits page
@views.route('/cancel-photo-item/<filename>/<siteID>/<projID>', methods=['GET'])
def cancel_photo_item(filename, siteID, projID):
    os.remove('static/uploads/' + filename)

    if siteID == '-1':
        return redirect(url_for("views.view_all_site_visits", projID=projID))
    return redirect(url_for("views.view_site_visit", siteID=siteID, sortby="desc", view='none'))


# Display uploaded photo to add photo page
@views.route('/uploaded-file/<filename>/', methods=['GET', 'POST'])
def uploaded_file(filename):
    if not session.get("user"):
        return redirect(url_for("views.error_401"))
    return send_from_directory( 'static/uploads/', filename)


# Ensure uploaded file is an image
def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# Rename file to 'PROJNUM-MM-DD-YYYY-TIME-FNAME-LNAME.jpg' format
def rename_upload(projID):
    pnum = Project.query.get(projID).proj_number
    timestamp = datetime.now()
    date = timestamp.strftime("%m-%d-%Y")
    time = timestamp.strftime("%H%M%S")
    filename = pnum + '-' + date + '-' + time + '-' + session["user"].get('name') + '.jpg'
    filename = secure_filename(filename.replace(' ', '-'))
    return filename


# Save a resized photo to display in thumbnails
def resize_photo(photo):
    fileString = (photo.filename).split('.jpg')
    if os.path.exists(f'static/uploads/{fileString[0]}_resized.jpg'):
        pass
    else:
        image = Image.open(f'static/uploads/{photo.filename}')
        image = image.resize((175,175),Image.LANCZOS)
        if image.mode in ("RGBA", "P"):
            image = image.convert("RGB")
        image.save(f'static/uploads/{fileString[0]}_resized.jpg', optimize=True, quality=95)


# Return list view of all site visits for a specific project
@views.route('/view-all-site-visits/<projID>/', methods=['GET', 'POST'])
def view_all_site_visits(projID):
    if not session.get("user"):
        return redirect(url_for("views.error_401"))
    project = Project.query.get(projID)
    if not project:
        return redirect(url_for("views.error_404"))
    # Once user is looking at another project, delete temp files
    dir = 'static/temp'
    for file in os.listdir(dir):
        os.remove(os.path.join(dir, file))
    sitevisits = SiteVisit.query.filter_by(projID=projID).order_by(SiteVisit.date.desc()).all()
    # add site visit to project
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        file = request.files['file']
        orientation = request.form['orientation']
        if file.filename == '': 
            flash('No selected file')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = rename_upload(projID)
            file.save(os.path.join('static/uploads/', filename))
            return render_template('add_photo.html', filename=filename, projID=projID, user=session["user"], siteID=-1, orientation=orientation)
    # get info for title & header
    proj_number = project.proj_number
    client = project.client
    prefixes = ["Village of ", "City of ", "Town of ", "County of "]
    # update 'READ' project for current user
    log_crud_project(proj_number, action='READ')

    # TOTAL PHOTOS PER SITE VISIT
    visitIDs = SiteVisit.query.with_entities(SiteVisit.sitevisitID).order_by(SiteVisit.date.desc()).all()
    # create dictionary {key=sitevisitID : value=0}
    total_photos = { visitID[0] : 0 for visitID in visitIDs }
    # update value = total number of photos for that site ID
    for visitID in total_photos.keys():
        count = PhotoItem.query.with_entities(PhotoItem.photoID).filter(PhotoItem.siteID.like(visitID)).all()
        total_photos[visitID] = len(count)

    # create dictionary with site visit date and # flagged items
    items_dct = {}
    for visit in sitevisits:
        photos = PhotoItem.query.filter_by(siteID=visit.sitevisitID).filter( (PhotoItem.is_immediate==True) |
                    (PhotoItem.is_nonimmediate==True) | (PhotoItem.is_flagged==True) ).all()
        count = len(photos)
        items_dct[visit.date] = count

    return render_template('view_all_site_visits.html', sitevisits=sitevisits, proj_number=proj_number, prefixes=prefixes,
        items_dct=items_dct, projID=projID, total_photos=total_photos, client=client, user=session["user"])


# Return calendar with site visits
@views.route('/calendar/<projID>', methods=['GET','POST'])
def calendar(projID):
    if not session.get("user"):
        return redirect(url_for("views.error_401"))
    project = Project.query.get(projID)
    if not project:
        return redirect(url_for("views.error_404"))
    visits = SiteVisit.query.filter_by(projID=projID).all()
    # add site visit to project
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        file = request.files['file']
        orientation = request.form['orientation']
        if file.filename == '': 
            flash('No selected file')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = rename_upload(projID)
            file.save(os.path.join('static/uploads/', filename))
            return render_template('add_photo.html', filename=filename, projID=projID, user=session["user"], siteID=-1, orientation=orientation)
    # get info for title & header
    proj_number = project.proj_number
    client = project.client
    prefixes = ["Village of ", "City of ", "Town of ", "County of "]
    
    return render_template('calendar.html', visits=visits, proj_number=proj_number, client=client, projID=projID, prefixes=prefixes, 
                            user=session["user"])


# Redirect to the upload photo page OR the add photo page
@views.route('/view-site-visit/<siteID>/<sortby>/<view>', methods=['GET', 'POST'])
def view_site_visit(siteID, sortby="desc", view='none'):
    if not session.get("user"):
        return redirect(url_for("views.error_401"))
    sitevisit = SiteVisit.query.filter_by(sitevisitID=siteID).first()
    if not sitevisit:
        return redirect(url_for("views.error_404"))
    projID = sitevisit.projID
    visit_date = sitevisit.date
    client = Project.query.get(projID).client
    proj_number = Project.query.get(projID).proj_number

    # add photo from main site visit page
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        file = request.files['file'] 
        orientation = request.form['orientation']
        if file.filename == '': 
            flash('No selected file')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = rename_upload(projID)
            file.save(os.path.join('static/uploads/', filename))
            return render_template('add_photo.html', filename=filename, projID=projID, user=session["user"], siteID=siteID, orientation=orientation)
    
    prefixes = ["Village of ", "City of ", "Town of ", "County of "]
    featuredphotos = PhotoItem.query.filter_by(siteID=siteID).filter( (PhotoItem.is_immediate==True) |
                    (PhotoItem.is_nonimmediate==True) | (PhotoItem.is_flagged==True) ).order_by(PhotoItem.time.desc()).all()
    
    if sortby == "desc":
        photoitems = PhotoItem.query.filter_by(siteID=siteID).order_by(PhotoItem.time.desc()).all()
    if sortby == "asc":
        photoitems = PhotoItem.query.filter_by(siteID=siteID).order_by(PhotoItem.time).all()
    
    # compress photos for thumbnails
    for photo in photoitems:
        resize_photo(photo)

    return render_template('view_site_visit.html', proj_number=proj_number, visit_date=visit_date, client=client, prefixes=prefixes,
            photoitems=photoitems, sitevisit=sitevisit, projID=projID, featuredphotos=featuredphotos, user=session["user"], view=view) 


# Convert query of all photos to list object that can be jsonified
def convert_photos_to_list(photos):
    converted_list = []
    for photo in photos:
        dict = {
            "photoID": photo.photoID,
            "siteID": photo.siteID,
            "filename": photo.filename,
            "author": photo.author,
            "time": photo.time,
            "latitude": photo.latitude,
            "longitude": photo.longitude,
            "comment": photo.comment,
            "is_flagged": photo.is_flagged,
            "is_immediate": photo.is_immediate,
            "is_nonimmediate": photo.is_nonimmediate,
            "orientation": photo.orientation
        }
        converted_list.append(dict)
    return converted_list


# View map of all photos taken for an individual site visit
@views.route('/view-site-visit-map/<siteID>', methods=['GET', 'POST'])
def view_site_visit_map(siteID):
    if not session.get("user"):
        return redirect(url_for("views.error_401"))
    sitevisit = SiteVisit.query.get(siteID)
    if not sitevisit:
        return redirect(url_for("views.error_404"))
    projID = sitevisit.projID
    # Add photo from map view page
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        file = request.files['file']
        orientation = request.form['orientation']
        if file.filename == '': 
            flash('No selected file')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = rename_upload(projID)
            file.save(os.path.join('static/uploads/', filename))
            return render_template('add_photo.html', filename=filename, projID=projID, user=session["user"], siteID=siteID, orientation=orientation)
    
    photo_items = PhotoItem.query.filter_by(siteID=siteID).all()
    photos = convert_photos_to_list(photo_items)
    visit_date = sitevisit.date
    client = Project.query.get(sitevisit.projID).client
    prefixes = ["Village of ", "City of ", "Town of ", "County of "]
    proj_number = Project.query.get(sitevisit.projID).proj_number
    lat = Project.query.get(sitevisit.projID).latitude
    lon = Project.query.get(sitevisit.projID).longitude
    
    # compress photos for thumbnails
    for photo in photo_items:
        resize_photo(photo)

    return render_template('view_site_visit_map.html',user=session["user"],proj_number=proj_number,lat=lat,lon=lon, client=client, projID=projID,
    visit_date=visit_date,prefixes=prefixes,sitevisit=sitevisit,photos=json.dumps(photos),photoitems=photo_items,apikey=api_key)


@views.route('/view-site-visit-photos/<siteID>', methods=['GET', 'POST'])
def view_site_visit_photos(siteID):
    if not session.get("user"):
        return redirect(url_for("views.error_401"))
    sitevisit = SiteVisit.query.get(siteID)
    if not sitevisit:
        return redirect(url_for("views.error_404"))
    projID = sitevisit.projID
    # add photo from gallery view
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        file = request.files['file']
        orientation = request.form['orientation']
        if file.filename == '': 
            flash('No selected file')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = rename_upload(projID)
            file.save(os.path.join('static/uploads/', filename))
            return render_template('add_photo.html', filename=filename, projID=projID, user=session["user"], siteID=siteID, orientation=orientation)
    # get info for title & header
    client = Project.query.get(projID).client
    proj_number = Project.query.get(projID).proj_number
    visit_date = sitevisit.date
    prefixes = ["Village of ", "City of ", "Town of ", "County of "]
    photoitems = PhotoItem.query.filter_by(siteID=siteID).order_by(PhotoItem.time.desc()).all()
    featuredphotos = PhotoItem.query.filter_by(siteID=siteID).filter( (PhotoItem.is_immediate==True) |
                    (PhotoItem.is_nonimmediate==True) | (PhotoItem.is_flagged==True) ).order_by(PhotoItem.time.desc()).all()
    # compress photos for thumbnails
    for photo in photoitems:
        resize_photo(photo)

    return render_template('view_site_visit_photos.html', proj_number=proj_number, visit_date=visit_date, client=client, prefixes=prefixes,
                    sitevisit=sitevisit, photoitems=photoitems, projID=projID, featuredphotos=featuredphotos, user=session["user"]) 


# If deleting photo from edit-photo-item, return to view-site-visit,
# if deleting photo from edit-site-visit, return to edit-site-visit
@views.route('/delete-photo-item/<id>/<page>', methods=['GET', 'POST'])
def delete_photo_item(id,page):
    if not session.get("user"):
        return redirect(url_for("views.error_401"))
    photo = PhotoItem.query.get(id)
    if not photo:
        return redirect(url_for("views.error_404"))
    log_crud_photoitem(id, action='DELETE')
    db.session.delete(photo)
    db.session.commit()
    fileStringDel = (photo.filename).split('.jpg')
    os.remove('static/uploads/' + photo.filename)
    os.remove('static/uploads/' + fileStringDel[0] + '_resized.jpg')
    flash("Photo item has been deleted.")
    if page == "view":
        return redirect(url_for('views.view_site_visit', siteID=photo.siteID, sortby='desc', view='none'))
    elif page == "edit":
        return redirect(url_for('views.edit_site_visit', siteID=photo.siteID))


@views.route('/edit-site-visit/<siteID>', methods=['GET'])
def edit_site_visit(siteID):
    if not session.get("user"):
        return redirect(url_for("views.error_401"))
    sitevisit = SiteVisit.query.get(siteID)
    if not sitevisit:
        return redirect(url_for("views.error_404"))
    # get info for title & header
    projID = sitevisit.projID
    visit_date = sitevisit.date
    client = Project.query.get(projID).client
    proj_number = Project.query.get(projID).proj_number
    prefixes = ["Village of ", "City of ", "Town of ", "County of "]
    featuredphotos = PhotoItem.query.filter_by(siteID=siteID).filter( (PhotoItem.is_immediate==True) |
                        (PhotoItem.is_nonimmediate==True) | (PhotoItem.is_flagged==True) ).order_by(PhotoItem.time.desc()).all()
    photoitems = PhotoItem.query.filter_by(siteID=siteID).order_by(PhotoItem.time.desc()).all()
    # compress photos for thumbnails
    for photo in photoitems:
        resize_photo(photo)
    
    return render_template('edit_site_visit.html', proj_number=proj_number, visit_date=visit_date, client=client, prefixes=prefixes, 
                    photoitems=photoitems, sitevisit=sitevisit, projID=projID, featuredphotos=featuredphotos, user=session["user"])     


# Get edit-site-visit changes per photo
def site_visit_changes(photos1, photos2, abrv):
    for photo in photos1:
        if photo not in photos2:
            caption = request.form[f'caption-{abrv}-{str(photo.photoID)}']
            action = request.form[f'action-{abrv}-{str(photo.photoID)}']
            text = action.split('-')[0]
            update = -1
            if photo.comment != caption or ((action != '' and text != 'None' and getattr(photo, text) != True) or (text == 'None' and (photo.is_immediate!=False or photo.is_nonimmediate!=False or photo.is_flagged!=False))):
                update = 1
            else:
                update = 0
            if photo.comment != caption:
                photo.comment = caption
            if action == f'is_flagged-{abrv}-{str(photo.photoID)}':
                photo.is_flagged = True
                photo.is_immediate = False
                photo.is_nonimmediate = False
            elif action == f'is_immediate-{abrv}-{str(photo.photoID)}':
                photo.is_immediate = True
                photo.is_flagged = False
                photo.is_nonimmediate = False
            elif action == f'is_nonimmediate-{abrv}-{str(photo.photoID)}':
                photo.is_nonimmediate = True
                photo.is_flagged = False
                photo.is_immediate = False
            elif action == f'None-{abrv}-{str(photo.photoID)}':
                photo.is_nonimmediate = False
                photo.is_flagged = False
                photo.is_immediate = False
            if update == 1:
                log_crud_photoitem(photo.photoID, action='UPDATE')
    db.session.commit()


# Save edit-site-visit changes for the site visit and each photo
@views.route('/save-site-visit/<siteID>/', methods=['GET', 'POST'])
def save_site_visit(siteID):
    if not session.get("user"):
        return redirect(url_for("views.error_401"))
    if request.method == 'POST':
        visit = SiteVisit.query.filter(SiteVisit.sitevisitID==siteID).first()
        if not visit:
            return redirect(url_for("views.error_404"))
        notes = request.form['notes']
        date = datetime.combine(datetime.strptime(request.form['date'],'%Y-%m-%d'), visit.date.time())

        if visit.notes != notes and visit.date == date:
            visit.notes = notes
            log_crud_sitevisit(visit.sitevisitID, action='UPDATE')
        elif visit.notes == notes and visit.date != date:
            visit.date = date
            log_crud_sitevisit(visit.sitevisitID, action='UPDATE')
        elif visit.notes != notes and visit.date != date:
            visit.notes = notes
            visit.date = date
            log_crud_sitevisit(visit.sitevisitID, action='UPDATE')
        elif visit.notes == notes and visit.date == date:
            pass
        db.session.commit()
                
        featuredphotos = PhotoItem.query.filter_by(siteID=siteID).filter( (PhotoItem.is_immediate==True) |
                    (PhotoItem.is_nonimmediate==True) | (PhotoItem.is_flagged==True) ).order_by(PhotoItem.time.desc()).all()
        allphotos = PhotoItem.query.filter_by(siteID=siteID).filter( (PhotoItem.is_immediate==False),
                    (PhotoItem.is_nonimmediate==False), (PhotoItem.is_flagged==False) ).order_by(PhotoItem.time.desc()).all()
        
        site_visit_changes(featuredphotos,allphotos,"ft")
        site_visit_changes(allphotos,featuredphotos,"all")

        flash('Success! Site visit has been updated.', category='success')
        return redirect(url_for("views.view_site_visit", siteID=siteID, sortby="desc", view='none'))


# Delete site visit and return to view all site visits page
@views.route('/delete-site-visit/<id>/', methods=['GET', 'POST'])
def delete_site_visit(id):
    if not session.get("user"):
        return redirect(url_for("views.error_401"))
    sitevisit = SiteVisit.query.get(id)
    if not sitevisit:
        return redirect(url_for("views.error_404"))
    photos = PhotoItem.query.filter_by(siteID=id)
    for photo in photos:
        log_crud_photoitem(photo.photoID, action='DELETE')
        db.session.delete(photo)
        db.session.commit()
        fileStringDel = (photo.filename).split('.jpg')
        os.remove('static/uploads/' + photo.filename)
        os.remove('static/uploads/' + fileStringDel[0] + '_resized.jpg')
    log_crud_sitevisit(id, action='DELETE')
    db.session.delete(sitevisit)
    db.session.commit()
    flash("Site visit has been deleted.")
    return redirect(url_for('views.view_all_site_visits', projID=sitevisit.projID))


# Retake photo item from view-photo-item page, add to db with same photo ID
@views.route('/retake-photo-item/<file>/<photoID>', methods=['GET', 'POST'])
def retake_photo_item(file, photoID):
    if not session.get("user"):
        return redirect(url_for("views.error_401"))
    if request.method == 'POST':
        photoitem = PhotoItem.query.get(photoID)
        if not photoitem:
            os.remove('static/uploads/' + file)
            return redirect(url_for("views.error_404"))
    # Obtain all information from add photo page
        comment = request.form['comment']
        action = request.form['action']
        if action == "": 
            if photoitem.is_flagged == True:
                action = 'is_flagged'
            elif photoitem.is_immediate == True:
                action = 'is_immediate'
            elif photoitem.is_nonimmediate == True:
                action = 'is_nonimmediate'
            else:
                action = 'None'
        siteID = request.form['siteID']
        latitude = request.form['latitude']
        longitude = request.form['longitude']
        orientation = request.form['orientation']
        time = datetime.now()
        filename = file
        author = session["user"].get("name")
    # Add photo to the selected site visit
        projID = request.form['projID']
        if siteID == '-1':
            date = time
            existing_site_visit = SiteVisit.query.filter(SiteVisit.projID==projID, SiteVisit.date.contains(date.strftime("%Y-%m-%d"))).first()
            if existing_site_visit:
                siteID = existing_site_visit.sitevisitID
    # Delete original photo
        log_crud_photoitem(photoID, action='DELETE')
        db.session.delete(photoitem)
        db.session.commit()
        fileStringDel = (photoitem.filename).split('.jpg')
        os.remove('static/uploads/' + photoitem.filename)
        os.remove('static/uploads/' + fileStringDel[0] + '_resized.jpg')
    # Create new photo item with same photoID and link to sitevisitID
        if action == 'is_flagged':
            new_photo_item = PhotoItem(photoID=photoID, time=time,comment=comment,filename=filename,siteID=siteID, orientation=orientation,
            author=author,latitude=latitude,longitude=longitude,is_flagged=True, is_immediate=False, is_nonimmediate=False)
        elif action == 'is_immediate':
            new_photo_item = PhotoItem(photoID=photoID, time=time,comment=comment,filename=filename,siteID=siteID, orientation=orientation,
            author=author,latitude=latitude,longitude=longitude,is_immediate=True, is_flagged=False, is_nonimmediate=False)
        elif action == 'is_nonimmediate':
            new_photo_item = PhotoItem(photoID=photoID, time=time,comment=comment,filename=filename,siteID=siteID, orientation=orientation,
            author=author,latitude=latitude,longitude=longitude,is_nonimmediate=True, is_flagged=False, is_immediate=False)
        else:
            new_photo_item = PhotoItem(photoID=photoID, time=time,comment=comment,filename=filename,siteID=siteID, orientation=orientation,
            author=author,latitude=latitude,longitude=longitude, is_nonimmediate=False, is_flagged=False, is_immediate=False)
        db.session.add(new_photo_item)
        db.session.commit()
        log_crud_photoitem(new_photo_item.photoID, action='CREATE')
        
    return redirect(url_for('views.view_site_visit', siteID=new_photo_item.siteID, sortby='desc', view=new_photo_item.filename))


# Remove filename from upload folder and redirect to view site visit or view all site visits page
@views.route('/cancel-retake/<filename>/<photoID>', methods=['GET'])
def cancel_retake(filename, photoID):
    os.remove('static/uploads/' + filename)
    return redirect(url_for("views.view_photo_item", photoID=photoID))


@views.route('/view-photo-item/<photoID>', methods=['GET', 'POST'])
def view_photo_item(photoID):
    if not session.get("user"):
        return redirect(url_for("views.error_401"))
    photoitem = PhotoItem.query.get(photoID)
    if not photoitem:
        return redirect(url_for("views.error_404"))
    # get info for title & header
    siteID = photoitem.siteID
    projID = SiteVisit.query.get(siteID).projID
    client = Project.query.get(projID).client
    proj_number = Project.query.get(projID).proj_number
    visit_date = SiteVisit.query.get(siteID).date
    prefixes = ["Village of ", "City of ", "Town of ", "County of "]
    # retake photo
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        file = request.files['file']
        orientation = request.form['orientation']
        if file.filename == '': 
            flash('No selected file')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = rename_upload(projID)
            file.save(os.path.join('static/uploads/', filename))
            return render_template('retake_photo_item.html', filename=filename, photoID=photoID, photoitem=photoitem, projID=projID,
                        user=session["user"], siteID=siteID, orientation=orientation)

    return render_template('view_photo_item.html', proj_number=proj_number, visit_date=visit_date, client=client, prefixes=prefixes,
                            siteID=siteID, photoitem=photoitem, projID=projID, user=session["user"],apikey=api_key)


@views.route('/edit-photo-item/<photoID>', methods=['GET'])
def edit_photo_item(photoID):
    if not session.get("user"):
        return redirect(url_for("views.error_401"))
    photoitem = PhotoItem.query.get(photoID)
    if not photoitem:
        return redirect(url_for("views.error_404"))
    # get info for title & header
    siteID = photoitem.siteID
    projID = SiteVisit.query.get(siteID).projID
    client = Project.query.get(projID).client
    proj_number = Project.query.get(projID).proj_number
    visit_date = SiteVisit.query.get(siteID).date
    prefixes = ["Village of ", "City of ", "Town of ", "County of "]
    
    return render_template('edit_photo_item.html', proj_number=proj_number, visit_date=visit_date, client=client, prefixes=prefixes,
                            siteID=siteID, photoitem=photoitem, projID=projID, user=session["user"])


@views.route('/save-photo-item/<photoID>', methods=['GET', 'POST'])
def save_photo_item(photoID):
    if not session.get("user"):
        return redirect(url_for("views.error_401"))
    if request.method == 'POST':
        photo = PhotoItem.query.filter(PhotoItem.photoID==photoID).first()
        if not photo:
            return redirect(url_for("views.error_404"))
        action = request.form['action']
        update = -1
        if photo.comment != request.form['comment'] or ((action != '' and action != 'None' and getattr(photo, action) != True) or (action == 'None' and (photo.is_immediate!=False or photo.is_nonimmediate!=False or photo.is_flagged!=False))):
            update = 1
        else:
            update = 0
        if photo.comment != request.form['comment']:
            photo.comment = request.form['comment']
        if action == 'is_flagged' and photo.is_flagged != True:
            photo.is_flagged=True
            photo.is_immediate=False
            photo.is_nonimmediate=False
        elif action == 'is_immediate' and photo.is_immediate != True:
            photo.is_immediate=True
            photo.is_flagged=False
            photo.is_nonimmediate=False
        elif action == 'is_nonimmediate' and photo.is_nonimmediate != True:
            photo.is_nonimmediate=True
            photo.is_flagged=False
            photo.is_immediate=False
        elif action == 'None' and (photo.is_nonimmediate != False or photo.is_flagged != False or photo.is_immediate != False):
            photo.is_nonimmediate=False
            photo.is_flagged=False
            photo.is_immediate=False
        if update == 1:
            log_crud_photoitem(photo.photoID, action='UPDATE')
        db.session.commit()
        flash('Success! Photo item has been updated.', category='success')
        return redirect(url_for("views.view_photo_item", photoID=photoID))


# Export project as zip file
@views.route('/export-project/<projID>', methods=['GET', 'POST'])
def export_project(projID):
    # Rename zip file
    pnum = Project.query.get(projID).proj_number
    time = datetime.now().strftime("%H%M%S")
    filename = pnum + '-' + time + '.zip'

    # Retrieve all photos for this project
    mem_file = BytesIO()
    zipObj = ZipFile(mem_file, 'w')

    sitevisits = SiteVisit.query.filter_by(projID=projID).all()
    for sitevisit in sitevisits:
        date = sitevisit.date.strftime("%m-%d-%Y")
        photos = PhotoItem.query.filter_by(siteID=sitevisit.sitevisitID).all()
        # Create csv file for each site visit
        string_buffer = io.StringIO()
        writer = csv.writer(string_buffer)
        writer.writerow(["Filename", "Comment", "Flagged", "Immediate", "Pending"])
        for photo in photos:
            basename = photo.filename
            zipObj.write('static/uploads/' + basename,  date + '\\' + basename)
            writer.writerow([photo.filename, photo.comment, photo.is_flagged, photo.is_immediate, photo.is_nonimmediate])
        zipObj.writestr(date + '_notes.csv', string_buffer.getvalue())

    zipObj.close()
    mem_file.seek(0)
    return send_file(mem_file, attachment_filename=filename, as_attachment=True)


# Export site visit as zip file
@views.route('/export-sitevisit/<siteID>', methods=['GET', 'POST'])
def export_sitevisit(siteID):
    # Rename zip file
    pid = SiteVisit.query.get(siteID).projID
    pnum = Project.query.get(pid).proj_number
    timestamp = datetime.now()
    date = SiteVisit.query.get(siteID).date.strftime("%m-%d-%Y")
    time = timestamp.strftime("%H%M%S")
    filename = pnum + '-' + date + '-' + time + '.zip'

    # Retrieve all photos and comments for this site visit
    mem_file = BytesIO()
    zipObj = ZipFile(mem_file, 'w')
    string_buffer = io.StringIO()
    writer = csv.writer(string_buffer)
    writer.writerow(["Filename", "Comment", "Flagged", "Immediate", "Pending"])
    photoitems = PhotoItem.query.filter_by(siteID=siteID).all()
    for photoitem in photoitems:
        basename = photoitem.filename
        zipObj.write('static/uploads/' + basename,  date + '\\' + basename)
        writer.writerow([photoitem.filename, photoitem.comment, photoitem.is_flagged, photoitem.is_immediate, photoitem.is_nonimmediate])
    
    zipObj.writestr(date + '_notes.csv', string_buffer.getvalue())
    zipObj.close()
    mem_file.seek(0)
    return send_file(mem_file, attachment_filename=filename, as_attachment=True)