# emailBlaster

I'm running out of room in my google account, and with over 20k gmail messages - need to clean things up more efficiently.

------------------------------------------------------

1. Set up a Google Cloud project and enable the Gmail API:

- Go to the Google Developers Console.
- Create a new project.
- Enable the Gmail API for your project.
- Create credentials (OAuth client ID) for a desktop application.
- Download the credentials file (credentials.json).

credentials.json file to be added in volume folder (mount this if using docker)
{
  "installed": {
    "client_id": "YOUR_CLIENT_ID.apps.googleusercontent.com",
    "project_id": "your-project-id",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_secret": "YOUR_CLIENT_SECRET",
    "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"]
  }
}

2. Local Build and Run:
```
pip install --no-cache-dir -r requirements.txt
python main.py --search "from:example@example.com" --delete
python main.py --search "invoice"
```

* TODO: fix docker. Docker not tested yet. Running locally, when logging in, token.json is placed alongside main.py file, and read from that location. Unable to login via browser in container.

3. Docker Build and Run:
```
docker build -t emailblaster:latest .
docker run --rm -it -v "$(pwd)/volume:/volume" --name=emailblaster emailblaster:latest  --search "from:example@example.com" --delete
docker run --rm -it -v "$(pwd)/volume:/volume" --name=emailblaster emailblaster:latest --search "invoice"
```
