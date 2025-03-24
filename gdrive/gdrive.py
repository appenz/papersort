from typing import Dict, List, Optional
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import os.path
import pickle
import os

SCOPES = ['https://www.googleapis.com/auth/drive.file']

class GDriveError(Exception):
    """Base exception for Google Drive operations."""
    pass

class GDrive:
    def __init__(self, credentials_path: str = "credentials.json") -> None:
        self.creds = None
        self.service = None
        self.docstore_folder = None
        
        # Load saved credentials if they exist
        if os.path.exists('token.pickle'):
            with open('token.pickle', 'rb') as token:
                self.creds = pickle.load(token)
        
        # If credentials are invalid or don't exist, let user authenticate
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
                self.creds = flow.run_local_server(port=0)
            
            # Save credentials for future use
            with open('token.pickle', 'wb') as token:
                pickle.dump(self.creds, token)
        
        self.service = build('drive', 'v3', credentials=self.creds)
        self._ensure_docstore_folder()

    def _ensure_docstore_folder(self) -> None:
        folder_name = os.getenv('DOCSTORE', 'Documents')
        # Strip 'googledrive:' prefix if present
        if folder_name.startswith('googledrive:'):
            folder_name = folder_name[len('googledrive:'):]
        try:
            # Just try to create the folder - if it exists, the API will handle it
            file_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            self.docstore_folder = self.service.files().create(
                body=file_metadata,
                fields='id, name'
            ).execute()
            
        except Exception as e:
            raise GDriveError(f"Failed to ensure docstore folder: {str(e)}")

    def _get_folder_id(self, path: str) -> str:
        if not path:
            return 'root'
            
        parts = [p for p in path.split('/') if p]
        current_parent = 'root'
        
        for part in parts:
            results = self.service.files().list(
                q=f"name='{part}' and mimeType='application/vnd.google-apps.folder' and '{current_parent}' in parents and trashed=false",
                fields="files(id, name)",
                spaces='drive'
            ).execute()
            
            items = results.get('files', [])
            if not items:
                raise GDriveError(f"Folder not found: {path}")
                
            current_parent = items[0]['id']
            
        return current_parent

    def create_folder(self, path: str, name: str) -> Dict:
        try:
            # Split path into parts and create each level
            parts = [p for p in path.split('/') if p]
            current_parent = 'root'
            
            for part in parts:
                # Search for existing folder
                results = self.service.files().list(
                    q=f"name='{part}' and mimeType='application/vnd.google-apps.folder' and '{current_parent}' in parents and trashed=false",
                    fields="files(id, name)",
                    spaces='drive'
                ).execute()
                
                items = results.get('files', [])
                
                if items:
                    current_parent = items[0]['id']
                else:
                    # Create new folder
                    file_metadata = {
                        'name': part,
                        'mimeType': 'application/vnd.google-apps.folder',
                        'parents': [current_parent]
                    }
                    folder = self.service.files().create(
                        body=file_metadata,
                        fields='id, name'
                    ).execute()
                    current_parent = folder['id']
            
            # Create the final folder
            file_metadata = {
                'name': name,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [current_parent]
            }
            return self.service.files().create(
                body=file_metadata,
                fields='id, name'
            ).execute()
            
        except Exception as e:
            raise GDriveError(f"Failed to create folder: {str(e)}")

    def list_items(self, path: str) -> List[Dict]:
        try:
            folder_id = self._get_folder_id(path)
            
            results = self.service.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                pageSize=100,
                fields="files(id, name, mimeType, size, modifiedTime)"
            ).execute()
            
            return results.get('files', [])
            
        except Exception as e:
            raise GDriveError(f"Failed to list items: {str(e)}") 