# Burke Field App

<img src="Field_App_Demo.gif" width=200><br>

## Table of Contents
1. [Description](#Description)
2. [Further Developments](#Further-Developments)
3. [Technologies & APIs](#Technologies-&-APIs)
4. [How To Run](#How-To-Run)
5. [AAS Deployment](#AAS-Deployment)

## Description
The web application contained in this repository was developed for specialists in the Environmental Resources department at Christopher B. Burke Engineering, Ltd. and intends to serve as a resource for departments across the company. Professionals on the field will use the app on a mobile device to optimize and expedite the documentation of field conditions and improve communication with clients. 

The core functionality of the app is to take photographs; collect location, orientation, date, time, and author data for each photo; link photos to a project and site visit; caption photos or visits with findings; flag photos as action items; and export select project or site visit data for in-office use, offline access, or status updates. A map is available for each site visit, populated with icon-sized version of the photos according to their geolocation, and an arrow to showcase the phone's orientation at the time of capture. Project, visit, and photo data may also be updated or deleted. 

Employees must sign in to the web app using their company Microsoft login so that CRUD functions performed by the user may be logged. To simplify collaboration and access, client and project data is available to all company staff across mobile and web and stored in one location. However, project delete permissions are restricted to the project author. The application is organized as Clients -> Projects -> Site Visits -> Photos. 

The company's current workflow involves regular data collection using available resources. Professionals in the Environmental Department, for example, mark off locations on paper maps, photograph field conditions on personal smartphones, and access photos on desktop via email or other cloud storage and file-sharing services. However, these methods of collecting, storing, and reporting data are time-consuming and may produce unsatisfactory results. Making phone calls to clients between field sites and the office, attempting to verbally indicate the location of problem areas, only being able to write notes in the office and provide clients with data long after site visits, and managing existing methods of data collection in adverse weather conditions are examples of problems that professionals face. 

With the essential tools now accessible in a single app, professionals will be able to quickly document field conditions, especially in the case of tough weather conditions, and continue updating information on-the-go.

## Further Developments
In future iterations of development, the following features will be implemented:
    - Desktop version
    - Markup photos
    - Collect weather data per photo
    - Generate company-standard site visit reports
    - Choose what data to export or include in report
    - Filter project data by department

## Technologies & APIs
**Microsoft Login:** utilizes Microsoft Authentication Library (MSAL), Microsoft Identity platform (Azure Active Directory), Microsoft Graph
    - https://docs.microsoft.com/en-us/azure/active-directory/develop/web-app-quickstart?pivots=devlang-python
    - https://github.com/Azure-Samples/ms-identity-python-webapp
    - *Login to Microsoft Azure portal (https://portal.azure.com/) for Client ID, Client Secret, and Tenant ID*
**Location Services:** utilizes HERE Map Rendering and HERE Geocoding
    - 250k API calls/month allowed (refer to HERE Maps documentation)
    - *Login to HERE Developer Portal (https://developer.here.com/login) for App ID and API Keys*
**ngrok**

## How To Run
1. Create a virtual environment with Python 3.8 or greater installed (Pickle Protocol 5 required)
2. Clone this repository
3. Run pip install -r requirements.txt
4. Run python app.py
5. If required, install flask_alchemy, PILLOW, and other libraries suggested from the terminal
6. Open app in browser at http://localhost:5000/ (due to Microsoft login, http://127.0.0.1:5000/ will not work)
7. Sign in with Microsoft account (if needed, manipulate settings for company access only)

## AAS Deployment
- Follow instructions at https://docs.microsoft.com/en-us/azure/app-service/quickstart-python?tabs=cmd&pivots=python-framework-flask
- In Visual Studio Code, install the Azure App Service extension
- Follow instructions at https://docs.microsoft.com/en-us/azure/developer/python/tutorial-deploy-app-service-on-linux-01 BUT...
- Continue through Step 6, ignoring Steps 2 and 4
- Complete timeout setting at https://docs.microsoft.com/en-us/answers/questions/168746/container-didn39t-respond-to-http-pings-on-port-80.html
- When website name changes, change the redirect URI in Microsoft Azure > App Registration > (app name) > authentication to https://<website_name>.azurewebsites.net/getAToken
