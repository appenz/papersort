"""Google Drive storage driver."""

from typing import Dict, List, Optional
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
import io
import os
import tempfile

from .base import StorageDriver, StorageError, FileInfo, FolderInfo
from utils.retry import (
    retry_on_transient_error,
    is_transient_network_error,
    TRANSIENT_HTTP_STATUS_CODES,
)


SCOPES = ['https://www.googleapis.com/auth/drive']


# ---------------------------------------------------------------------------
# Google Drive Retry Configuration
# ---------------------------------------------------------------------------

def _is_retryable_gdrive_error(exc: Exception) -> bool:
    """Determine if a Google Drive API error should be retried."""
    if isinstance(exc, HttpError):
        status_code = exc.resp.status
        return status_code in TRANSIENT_HTTP_STATUS_CODES
    return is_transient_network_error(exc)


def _log_retry(exc: Exception, attempt: int, delay: float) -> None:
    """Log when a retry is about to happen."""
    if isinstance(exc, HttpError):
        error_desc = f"HTTP {exc.resp.status}"
    else:
        error_desc = type(exc).__name__
    print(f"  [Retry] {error_desc} on attempt {attempt}, retrying in {delay:.1f}s...")


def _execute_with_retry(request):
    """Execute a Google Drive API request with automatic retry."""
    @retry_on_transient_error(
        is_retryable=_is_retryable_gdrive_error,
        max_retries=5,
        base_delay=1.0,
        max_delay=60.0,
        on_retry=_log_retry,
    )
    def execute():
        return request.execute()
    return execute()


def _download_with_retry(request, destination):
    """Download a file from Google Drive with automatic retry."""
    downloader = MediaIoBaseDownload(destination, request)
    done = False
    
    while not done:
        @retry_on_transient_error(
            is_retryable=_is_retryable_gdrive_error,
            max_retries=5,
            base_delay=1.0,
            max_delay=60.0,
            on_retry=_log_retry,
        )
        def download_next_chunk():
            return downloader.next_chunk()
        
        status, done = download_next_chunk()


def _escape_query_value(value: str) -> str:
    """Escape a value for use in Google Drive API query strings."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


class GDriveDriver(StorageDriver):
    """Storage driver for Google Drive.
    
    Uses service account authentication. All paths are relative to
    the root_folder_id provided at construction.
    """
    
    def __init__(self, root_folder_id: str,
                 service_account_file: str = "service_account_key.json") -> None:
        """Initialize Google Drive storage driver.
        
        Args:
            root_folder_id: Google Drive folder ID to use as root
            service_account_file: Path to service account credentials JSON
            
        Raises:
            StorageError: If authentication fails or folder can't be accessed
        """
        self.root_folder_id = root_folder_id
        self._root_folder_name: Optional[str] = None
        
        try:
            self.creds = service_account.Credentials.from_service_account_file(
                service_account_file, scopes=SCOPES
            )
            self.service = build('drive', 'v3', credentials=self.creds)
            
            # Verify folder exists and get its name
            result = _execute_with_retry(self.service.files().get(
                fileId=root_folder_id,
                fields="id, name",
                supportsAllDrives=True,
            ))
            self._root_folder_name = result['name']
            
        except Exception as e:
            raise StorageError(f"Failed to initialize Google Drive: {e}")
    
    @property
    def display_name(self) -> str:
        name = self._root_folder_name or self.root_folder_id
        return f"{name} (Google Drive)"
    
    def _get_folder_id(self, path: str) -> str:
        """Get folder ID for a path relative to root folder."""
        if not path:
            return self.root_folder_id
            
        parts = [p for p in path.split('/') if p]
        current_parent = self.root_folder_id
        
        for part in parts:
            escaped_part = _escape_query_value(part)
            results = _execute_with_retry(self.service.files().list(
                q=f"name='{escaped_part}' and mimeType='application/vnd.google-apps.folder' and '{current_parent}' in parents and trashed=false",
                fields="files(id, name)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ))
            
            items = results.get('files', [])
            if not items:
                raise StorageError(f"Folder not found: {path}")
            current_parent = items[0]['id']
            
        return current_parent
    
    def _get_item_by_path(self, path: str) -> Optional[Dict]:
        """Get item metadata by path relative to root folder."""
        if not path:
            return None
            
        parts = [p for p in path.split('/') if p]
        if not parts:
            return None
            
        current_parent = self.root_folder_id
        item = None
        
        try:
            for i, part in enumerate(parts):
                is_last = (i == len(parts) - 1)
                escaped_part = _escape_query_value(part)
                
                if is_last:
                    q = f"name='{escaped_part}' and '{current_parent}' in parents and trashed=false"
                else:
                    q = f"name='{escaped_part}' and mimeType='application/vnd.google-apps.folder' and '{current_parent}' in parents and trashed=false"
                
                results = _execute_with_retry(self.service.files().list(
                    q=q,
                    fields="files(id, name, mimeType, size, modifiedTime)",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                ))
                
                items = results.get('files', [])
                if not items:
                    return None
                    
                item = items[0]
                current_parent = item['id']
            
            return item
        except Exception:
            return None
    
    def list_files(self, path: str = "", recursive: bool = False,
                   extension: Optional[str] = None) -> List[FileInfo]:
        """List files at the given path."""
        try:
            folder_id = self._get_folder_id(path)
        except StorageError:
            raise
        
        extension_lower = extension.lower() if extension else None
        results = []
        
        if recursive:
            self._list_files_recursive(folder_id, path, extension_lower, results)
        else:
            self._list_files_flat(folder_id, path, extension_lower, results)
        
        return results
    
    def _list_files_flat(self, folder_id: str, base_path: str,
                         extension: Optional[str], results: List[FileInfo]) -> None:
        """List files in a single folder (non-recursive)."""
        page_token = None
        
        while True:
            response = _execute_with_retry(self.service.files().list(
                q=f"'{folder_id}' in parents and trashed=false and mimeType!='application/vnd.google-apps.folder'",
                pageSize=100,
                fields="nextPageToken, files(id, name, size)",
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ))
            
            for item in response.get('files', []):
                if extension and not item['name'].lower().endswith(extension):
                    continue
                
                item_path = f"{base_path}/{item['name']}" if base_path else item['name']
                results.append(FileInfo(
                    path=item_path,
                    name=item['name'],
                    size=int(item.get('size', 0)) if item.get('size') else None,
                    id=item['id']
                ))
            
            page_token = response.get('nextPageToken')
            if not page_token:
                break
    
    def _list_files_recursive(self, folder_id: str, base_path: str,
                              extension: Optional[str], results: List[FileInfo]) -> None:
        """List files recursively including subfolders."""
        page_token = None
        
        while True:
            response = _execute_with_retry(self.service.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                pageSize=100,
                fields="nextPageToken, files(id, name, mimeType, size)",
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ))
            
            for item in response.get('files', []):
                item_path = f"{base_path}/{item['name']}" if base_path else item['name']
                
                if item['mimeType'] == 'application/vnd.google-apps.folder':
                    # Recurse into subfolder
                    self._list_files_recursive(item['id'], item_path, extension, results)
                else:
                    # It's a file
                    if extension and not item['name'].lower().endswith(extension):
                        continue
                    
                    results.append(FileInfo(
                        path=item_path,
                        name=item['name'],
                        size=int(item.get('size', 0)) if item.get('size') else None,
                        id=item['id']
                    ))
            
            page_token = response.get('nextPageToken')
            if not page_token:
                break
    
    def list_folders(self, path: str = "") -> List[FolderInfo]:
        """List immediate subfolders at the given path."""
        try:
            folder_id = self._get_folder_id(path)
        except StorageError:
            raise
        
        results = []
        page_token = None
        
        while True:
            response = _execute_with_retry(self.service.files().list(
                q=f"'{folder_id}' in parents and trashed=false and mimeType='application/vnd.google-apps.folder'",
                pageSize=100,
                fields="nextPageToken, files(id, name)",
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ))
            
            for item in response.get('files', []):
                item_path = f"{path}/{item['name']}" if path else item['name']
                results.append(FolderInfo(
                    path=item_path,
                    name=item['name'],
                    id=item['id']
                ))
            
            page_token = response.get('nextPageToken')
            if not page_token:
                break
        
        return results
    
    def file_exists(self, path: str) -> bool:
        """Check if a file exists at the given path."""
        item = self._get_item_by_path(path)
        return item is not None
    
    def read_text(self, path: str) -> str:
        """Read a text file and return its contents."""
        item = self._get_item_by_path(path)
        if not item:
            raise StorageError(f"File not found: {path}")
        
        if item.get('mimeType') == 'application/vnd.google-apps.folder':
            raise StorageError(f"Cannot read a folder: {path}")
        
        try:
            request = self.service.files().get_media(fileId=item['id'])
            buffer = io.BytesIO()
            _download_with_retry(request, buffer)
            buffer.seek(0)
            return buffer.read().decode('utf-8')
        except Exception as e:
            raise StorageError(f"Failed to read file {path}: {e}")
    
    def download_to_temp(self, path: str) -> str:
        """Download a file to a temporary location."""
        item = self._get_item_by_path(path)
        if not item:
            raise StorageError(f"File not found: {path}")
        
        if item.get('mimeType') == 'application/vnd.google-apps.folder':
            raise StorageError(f"Cannot download a folder: {path}")
        
        try:
            # Create temp file with appropriate extension
            _, ext = os.path.splitext(item['name'])
            temp_fd, temp_path = tempfile.mkstemp(suffix=ext)
            os.close(temp_fd)
            
            request = self.service.files().get_media(fileId=item['id'])
            with open(temp_path, 'wb') as f:
                _download_with_retry(request, f)
            
            return temp_path
        except Exception as e:
            raise StorageError(f"Failed to download file {path}: {e}")
    
    def upload(self, local_path: str, dest_path: str) -> None:
        """Upload a local file to Google Drive."""
        try:
            parts = [p for p in dest_path.split('/') if p]
            if not parts:
                raise StorageError("Invalid destination path")
            
            filename = parts[-1]
            folder_path = '/'.join(parts[:-1]) if len(parts) > 1 else ''
            
            # Ensure parent folders exist
            parent_id = self._ensure_folders_exist(folder_path)
            
            # Check if file already exists
            escaped_filename = _escape_query_value(filename)
            results = _execute_with_retry(self.service.files().list(
                q=f"name='{escaped_filename}' and '{parent_id}' in parents and trashed=false",
                fields="files(id, name)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ))
            
            existing_files = results.get('files', [])
            media = MediaFileUpload(local_path, resumable=True)
            
            if existing_files:
                # Update existing file
                file_id = existing_files[0]['id']
                _execute_with_retry(self.service.files().update(
                    fileId=file_id,
                    media_body=media,
                    supportsAllDrives=True,
                ))
            else:
                # Create new file
                file_metadata = {
                    'name': filename,
                    'parents': [parent_id]
                }
                _execute_with_retry(self.service.files().create(
                    body=file_metadata,
                    media_body=media,
                    supportsAllDrives=True,
                ))
        except StorageError:
            raise
        except Exception as e:
            raise StorageError(f"Failed to upload file: {e}")
    
    def _ensure_folders_exist(self, folder_path: str) -> str:
        """Ensure all folders in path exist, creating if needed. Returns final folder ID."""
        if not folder_path:
            return self.root_folder_id
        
        parts = [p for p in folder_path.split('/') if p]
        current_parent = self.root_folder_id
        
        for part in parts:
            escaped_part = _escape_query_value(part)
            results = _execute_with_retry(self.service.files().list(
                q=f"name='{escaped_part}' and mimeType='application/vnd.google-apps.folder' and '{current_parent}' in parents and trashed=false",
                fields="files(id, name)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ))
            
            items = results.get('files', [])
            if items:
                current_parent = items[0]['id']
            else:
                # Create folder
                file_metadata = {
                    'name': part,
                    'mimeType': 'application/vnd.google-apps.folder',
                    'parents': [current_parent]
                }
                folder = _execute_with_retry(self.service.files().create(
                    body=file_metadata,
                    fields='id',
                    supportsAllDrives=True,
                ))
                current_parent = folder['id']
        
        return current_parent
    
    def move(self, src_path: str, dest_folder: str) -> None:
        """Move a file to a different folder."""
        item = self._get_item_by_path(src_path)
        if not item:
            raise StorageError(f"Source file not found: {src_path}")
        
        if item.get('mimeType') == 'application/vnd.google-apps.folder':
            raise StorageError(f"Cannot move a folder with this method: {src_path}")
        
        try:
            # Get current parent folder ID
            src_parts = [p for p in src_path.split('/') if p]
            if len(src_parts) > 1:
                src_folder_path = '/'.join(src_parts[:-1])
                old_parent_id = self._get_folder_id(src_folder_path)
            else:
                old_parent_id = self.root_folder_id
            
            # Get destination folder ID
            new_parent_id = self._get_folder_id(dest_folder)
            
            # Move the file
            _execute_with_retry(self.service.files().update(
                fileId=item['id'],
                addParents=new_parent_id,
                removeParents=old_parent_id,
                supportsAllDrives=True,
            ))
        except StorageError:
            raise
        except Exception as e:
            raise StorageError(f"Failed to move file: {e}")
    
    def delete(self, path: str) -> None:
        """Move a file or folder to Trash."""
        item = self._get_item_by_path(path)
        if not item:
            raise StorageError(f"Item not found: {path}")
        
        try:
            _execute_with_retry(self.service.files().update(
                fileId=item['id'],
                body={'trashed': True},
                supportsAllDrives=True,
            ))
        except Exception as e:
            raise StorageError(f"Failed to delete item: {e}")
    
    def sanitize_filename(self, name: str) -> str:
        """Sanitize a filename for Google Drive.
        
        Google Drive is very permissive - only / is truly forbidden.
        """
        return name.replace('/', '-')
    
    # =========================================================================
    # Legacy compatibility methods (used by existing code)
    # =========================================================================
    
    @property
    def root_folder(self) -> Dict:
        """Legacy property for compatibility."""
        return {'id': self.root_folder_id, 'name': self._root_folder_name}
    
    def list_items(self, path: str) -> List[Dict]:
        """Legacy method: list all items (files and folders) at path."""
        try:
            folder_id = self._get_folder_id(path)
        except StorageError:
            raise
        
        all_items = []
        page_token = None
        
        while True:
            results = _execute_with_retry(self.service.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                pageSize=100,
                fields="nextPageToken, files(id, name, mimeType, size, modifiedTime)",
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ))
            
            all_items.extend(results.get('files', []))
            page_token = results.get('nextPageToken')
            
            if not page_token:
                break
        
        return all_items
    
    def list_files_recursive(self, folder_id: Optional[str] = None,
                             extension: str = ".pdf") -> List[Dict]:
        """Legacy method for backward compatibility."""
        if folder_id is None:
            folder_id = self.root_folder_id
        
        files = self.list_files(path="", recursive=True, extension=extension)
        
        # Convert to legacy format
        return [{'id': f.id, 'name': f.name, 'path': f.path} for f in files]
    
    def upload_file(self, local_path: str, drive_path: str) -> Dict:
        """Legacy method for backward compatibility."""
        self.upload(local_path, drive_path)
        return {}
    
    def move_file(self, source_path: str, dest_folder_path: str) -> Dict:
        """Legacy method for backward compatibility."""
        self.move(source_path, dest_folder_path)
        return {}
    
    def delete_item(self, drive_path: str) -> None:
        """Legacy method for backward compatibility."""
        self.delete(drive_path)
    
    def read_file_content(self, drive_path: str) -> str:
        """Legacy method for backward compatibility."""
        return self.read_text(drive_path)
