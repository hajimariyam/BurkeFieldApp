# Burke Field App

# Description
The mobile web app under development at Christopher B. Burke Engineering, Ltd. is
intended to serve as a resource for departments within the company. The core functionality of
the app will be to take a photo, link it to a project, collect location, orientation, date, and time
data for each photo, mark the urgency of action items, caption photos, and export
selected data. The app aims to optimize and expedite data collection on the field and improve
communication with clients.

Departments will use the mobile app on the field to collect data regarding field conditions,
including photos, notes, and action items. In the office, the web app can be used to access
select data, export site visits and projects, and generate photo exhibits/formal reports.

Photos taken within the app will automatically be stored with location, orientation, date, and time. 
Site visit-specific site maps are populated with icon-sized photos according to their geolocation, and
an arrow to showcase the phones orientation at photo capture.

Raw project data, regardless of the collecting user, is accessible to all company staff across
mobile and web and stored in one location, simplifying collaboration and data usage. Project
history is saved/logged and all edits are marked with user data. The app is organized by
project, and data within each project is sorted per date of inspection/site visit. The accessibility
of all essential tools within a single app will allow professionals to quickly document conditions
on the field, especially in the case of tough weather conditions, and continuously update information.


# How to Run
1. Create a virtual environment with Python 3.8 or greater installed (pickle protocol 5 required)
2. Clone this repository
3. Run pip install -r requirements.txt
4. Run python app.py
5. If required, install flask_alchemy, PILLOW, and other libraries suggested from the terminal
6. Open app in browser at http://localhost:5000/
7. Sign in with CBBEL microsoft account


# Microsoft Login
Refer to https://docs.microsoft.com/en-us/azure/active-directory/develop/quickstart-v2-python-webapp for set up
- One CBBEL employee account will be needed
- Use the existing app_config.py file to edit client ID, secret, and authority
- Step 1: #5, select 'Accounts in any organizational directory' for cbbel access only
- Step 2: Download is NOT required, all required files are included in repo
- Step 3: #1, #2 can be ignored


# AAS Deployment
- Follow instructions at https://docs.microsoft.com/en-us/azure/app-service/quickstart-python?tabs=cmd&pivots=python-framework-flask
- In Visual Studio Code, install the Azure App Service extension
- Follow instructions at https://docs.microsoft.com/en-us/azure/developer/python/tutorial-deploy-app-service-on-linux-01 BUT...
- continue through step 6 and ignore steps #2 and #4
- complete timeout setting at https://docs.microsoft.com/en-us/answers/questions/168746/container-didn39t-respond-to-http-pings-on-port-80.html


# Requirements/Notes
- For hosting, microsoft login requires https, NOT http
- 250k API calls/month allowed (refer to HERE Maps documentation)
- Current microsoft login will expire within 3 months
- when website name changes, change the redirect URI in Azure > App Registration > (app name) > authentication to https://<website_name>.azurewebsites.net/getAToken


# Errors
- mobile uploads are sideways in gallery view
- for some small window sizes, the export icon is not aligned when viewing a site visit


# To Do
- sharing feature
