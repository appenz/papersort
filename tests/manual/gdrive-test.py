import os

from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
SERVICE_ACCOUNT_FILE = "service_account_key.json"
FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID")

creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES
)

drive = build("drive", "v3", credentials=creds)

q = f"'{FOLDER_ID}' in parents and trashed=false"
resp = drive.files().list(
    q=q,
    fields="files(id,name,mimeType,modifiedTime,size),nextPageToken",
    pageSize=1000,
    supportsAllDrives=True,
    includeItemsFromAllDrives=True,
).execute()

print(resp)

for f in resp.get("files", []):
    print(f"{f['name']}  ({f['id']})  {f['mimeType']}")
