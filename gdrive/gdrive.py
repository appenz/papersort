from typing import Dict, List, Optional, Tuple
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
import io
import os
import tempfile

from utils.retry import (
    retry_on_transient_error,
    is_transient_network_error,
    TRANSIENT_HTTP_STATUS_CODES,
)

SCOPES = ['https://www.googleapis.com/auth/drive']


# ---------------------------------------------------------------------------
# Google Drive Retry Configuration
# ---------------------------------------------------------------------------
# Google's APIs can fail with transient errors. This section configures
# automatic retry behavior specific to Google Drive.

def _is_retryable_gdrive_error(exc: Exception) -> bool:
    """
    Determine if a Google Drive API error should be retried.
    
    We retry on:
    - HTTP 429 (rate limited by Google)
    - HTTP 5xx (Google's servers having issues)
    - Network errors (connection reset, timeout, etc.)
    
    We do NOT retry on:
    - HTTP 4xx (except 429): These are client errors like "not found" or
      "permission denied" that won't be fixed by retrying
    - Other exceptions: Programming errors, invalid arguments, etc.
    
    Args:
        exc: The exception raised by the API call
        
    Returns:
        True if this is a transient error worth retrying
    """
    # Check for Google API HTTP errors
    if isinstance(exc, HttpError):
        # HttpError has a resp attribute with the HTTP status code
        status_code = exc.resp.status
        return status_code in TRANSIENT_HTTP_STATUS_CODES
    
    # Check for general network errors (connection reset, timeout, etc.)
    return is_transient_network_error(exc)


def _log_retry(exc: Exception, attempt: int, delay: float) -> None:
    """
    Log when a retry is about to happen.
    
    This helps with debugging transient failures - you can see in the output
    that retries are happening rather than silent failures.
    
    Args:
        exc: The exception that caused the retry
        attempt: Which attempt just failed (1 = first attempt)
        delay: How many seconds we'll wait before retrying
    """
    # Extract a short description of the error
    if isinstance(exc, HttpError):
        error_desc = f"HTTP {exc.resp.status}"
    else:
        error_desc = type(exc).__name__
    
    print(f"  [Retry] {error_desc} on attempt {attempt}, retrying in {delay:.1f}s...")


def _execute_with_retry(request):
    """
    Execute a Google Drive API request with automatic retry on transient errors.
    
    This is the core helper that wraps all Google Drive API calls. Instead of
    calling request.execute() directly (which fails immediately on errors),
    we wrap it with exponential backoff retry logic.
    
    Args:
        request: A Google API request object (from files().list(), files().get(), etc.)
        
    Returns:
        The API response (same as request.execute() would return)
        
    Raises:
        HttpError: If a non-retryable HTTP error occurs, or all retries exhausted
        GDriveError: Wrapped in calling code for consistent error handling
        
    Example:
        # Instead of:
        result = self.service.files().list(q=query).execute()
        
        # We do:
        result = _execute_with_retry(self.service.files().list(q=query))
    """
    # Create a retry-wrapped version of the execute method
    # We use the decorator as a function here rather than with @ syntax
    @retry_on_transient_error(
        is_retryable=_is_retryable_gdrive_error,
        max_retries=5,        # Try up to 6 times total
        base_delay=1.0,       # Start with 1 second delay
        max_delay=60.0,       # Never wait more than 60 seconds
        on_retry=_log_retry,  # Log each retry attempt
    )
    def execute():
        return request.execute()
    
    return execute()


def _download_with_retry(request, destination):
    """
    Download a file from Google Drive with automatic retry on transient errors.
    
    Google Drive downloads work differently from regular API calls - they use
    MediaIoBaseDownload which fetches the file in chunks. Each chunk fetch can
    fail with transient errors, so we need retry logic here too.
    
    This function handles the entire download process, retrying individual chunks
    if they fail, and restarting the download if necessary.
    
    Args:
        request: A get_media request object from service.files().get_media()
        destination: A file-like object to write the downloaded content to.
                    Must support write() and seek(). Can be a file opened in 'wb'
                    mode or a BytesIO buffer.
        
    Raises:
        HttpError: If a non-retryable HTTP error occurs, or all retries exhausted
        
    Example:
        request = self.service.files().get_media(fileId=file_id)
        with open(local_path, 'wb') as f:
            _download_with_retry(request, f)
    """
    downloader = MediaIoBaseDownload(destination, request)
    done = False
    
    while not done:
        # Wrap each chunk download with retry logic
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
    """Escape a value for use in Google Drive API query strings.
    
    Single quotes must be escaped with backslash in query parameters.
    """
    return value.replace("\\", "\\\\").replace("'", "\\'")


def parse_storage_uri(uri: str) -> Tuple[str, str]:
    """Parse 'gdrive:folder_id' or 'local:path' into (type, value).
    
    Args:
        uri: Storage URI with prefix (e.g., 'gdrive:abc123' or 'local:inbox')
        
    Returns:
        Tuple of (storage_type, value) where storage_type is 'gdrive' or 'local'
        
    Raises:
        ValueError: If URI doesn't start with a valid prefix
    """
    if uri.startswith("gdrive:"):
        return ("gdrive", uri[7:])
    elif uri.startswith("local:"):
        return ("local", uri[6:])
    else:
        raise ValueError(f"Invalid storage URI: {uri}. Must start with 'gdrive:' or 'local:'")


class GDriveError(Exception):
    """Base exception for Google Drive operations."""
    pass

class GDrive:
    def __init__(self, service_account_file: str = "service_account_key.json", root_folder_id: Optional[str] = None) -> None:
        """Initialize GDrive client.
        
        Args:
            service_account_file: Path to service account credentials JSON file
            root_folder_id: Optional folder ID to use as root. If not provided,
                           must call set_root_folder() before using path-based methods.
        """
        self.creds = None
        self.service = None
        self.root_folder_id = None
        self.root_folder = None
        
        # Use service account credentials
        self.creds = service_account.Credentials.from_service_account_file(
            service_account_file, scopes=SCOPES
        )
        
        self.service = build('drive', 'v3', credentials=self.creds)
        
        if root_folder_id:
            self.set_root_folder(root_folder_id)

    def set_root_folder(self, folder_id: str) -> None:
        """Set the root folder for all path-based operations.
        
        Args:
            folder_id: Google Drive folder ID to use as root
            
        Raises:
            GDriveError: If folder doesn't exist or can't be accessed
        """
        try:
            # Verify the folder exists and we have access
            result = _execute_with_retry(self.service.files().get(
                fileId=folder_id,
                fields="id, name",
                supportsAllDrives=True,
            ))
            
            self.root_folder_id = result['id']
            self.root_folder = result
            
        except Exception as e:
            raise GDriveError(f"Failed to access folder {folder_id}: {str(e)}")

    # Backward compatibility alias
    @property
    def docstore_folder_id(self) -> Optional[str]:
        return self.root_folder_id
    
    @docstore_folder_id.setter
    def docstore_folder_id(self, value: str) -> None:
        self.root_folder_id = value

    def _get_folder_id(self, path: str) -> str:
        """Get folder ID for a path relative to the docstore folder."""
        if not path:
            return self.docstore_folder_id
            
        parts = [p for p in path.split('/') if p]
        current_parent = self.docstore_folder_id
        
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
                raise GDriveError(f"Folder not found: {path}")
                
            current_parent = items[0]['id']
            
        return current_parent

    def create_folder(self, path: str, name: str) -> Dict:
        """Creates a new folder relative to docstore. Creates parent folders recursively if they don't exist."""
        try:
            # Split path into parts and create each level
            parts = [p for p in path.split('/') if p]
            current_parent = self.docstore_folder_id
            
            for part in parts:
                # Search for existing folder
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
                    # Create new folder
                    file_metadata = {
                        'name': part,
                        'mimeType': 'application/vnd.google-apps.folder',
                        'parents': [current_parent]
                    }
                    folder = _execute_with_retry(self.service.files().create(
                        body=file_metadata,
                        fields='id, name',
                        supportsAllDrives=True,
                    ))
                    current_parent = folder['id']
            
            # Check if the final folder already exists
            escaped_name = _escape_query_value(name)
            results = _execute_with_retry(self.service.files().list(
                q=f"name='{escaped_name}' and mimeType='application/vnd.google-apps.folder' and '{current_parent}' in parents and trashed=false",
                fields="files(id, name)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ))
            
            items = results.get('files', [])
            if items:
                return items[0]
            
            # Create the final folder
            file_metadata = {
                'name': name,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [current_parent]
            }
            return _execute_with_retry(self.service.files().create(
                body=file_metadata,
                fields='id, name',
                supportsAllDrives=True,
            ))
            
        except Exception as e:
            raise GDriveError(f"Failed to create folder: {str(e)}")

    def list_items(self, path: str) -> List[Dict]:
        """Lists contents of a directory with pagination support."""
        try:
            folder_id = self._get_folder_id(path)
            
            all_files = []
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
                
                all_files.extend(results.get('files', []))
                page_token = results.get('nextPageToken')
                
                if not page_token:
                    break
            
            return all_files
            
        except Exception as e:
            raise GDriveError(f"Failed to list items: {str(e)}")

    def get_item_by_path(self, path: str) -> Optional[Dict]:
        """Retrieves metadata for a specific item by path relative to docstore folder."""
        if not path:
            return None
            
        parts = [p for p in path.split('/') if p]
        if not parts:
            return None
            
        current_parent = self.docstore_folder_id
        item = None
        
        try:
            for i, part in enumerate(parts):
                is_last = (i == len(parts) - 1)
                escaped_part = _escape_query_value(part)
                
                # For intermediate parts, only search folders
                # For the last part, search any type
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
            
        except Exception as e:
            raise GDriveError(f"Failed to get item by path: {str(e)}")

    def file_exists(self, path: str) -> bool:
        """Check if a file exists at the given path relative to docstore folder.
        
        Args:
            path: Path to check (e.g., "Financial/Bank Accounts/Statement 2024.pdf")
            
        Returns:
            True if file exists, False otherwise
        """
        try:
            item = self.get_item_by_path(path)
            return item is not None
        except GDriveError:
            return False

    def upload_file(self, local_path: str, drive_path: str) -> Dict:
        """Uploads a file to Google Drive relative to docstore folder. Supports chunked upload for large files."""
        try:
            # Split drive_path into folder path and filename
            parts = [p for p in drive_path.split('/') if p]
            if not parts:
                raise GDriveError("Invalid drive path")
            
            filename = parts[-1]
            folder_path = '/'.join(parts[:-1]) if len(parts) > 1 else ''
            
            # Get or create the parent folder
            if folder_path:
                # Ensure parent folders exist
                folder_parts = folder_path.split('/')
                current_parent = self.docstore_folder_id
                
                for part in folder_parts:
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
                            fields='id, name',
                            supportsAllDrives=True,
                        ))
                        current_parent = folder['id']
                
                parent_id = current_parent
            else:
                parent_id = self.docstore_folder_id
            
            # Check if file already exists (to update instead of create duplicate)
            escaped_filename = _escape_query_value(filename)
            results = _execute_with_retry(self.service.files().list(
                q=f"name='{escaped_filename}' and '{parent_id}' in parents and trashed=false",
                fields="files(id, name)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ))
            
            existing_files = results.get('files', [])
            
            # Prepare the media upload with resumable=True for large files
            media = MediaFileUpload(local_path, resumable=True)
            
            if existing_files:
                # Update existing file
                file_id = existing_files[0]['id']
                return _execute_with_retry(self.service.files().update(
                    fileId=file_id,
                    media_body=media,
                    fields='id, name, mimeType, size, modifiedTime',
                    supportsAllDrives=True,
                ))
            else:
                # Create new file
                file_metadata = {
                    'name': filename,
                    'parents': [parent_id]
                }
                return _execute_with_retry(self.service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields='id, name, mimeType, size, modifiedTime',
                    supportsAllDrives=True,
                ))
            
        except Exception as e:
            raise GDriveError(f"Failed to upload file: {str(e)}")

    def download_file(self, drive_path: str, local_path: str) -> None:
        """Downloads a file from Google Drive to a local path."""
        try:
            item = self.get_item_by_path(drive_path)
            if not item:
                raise GDriveError(f"File not found: {drive_path}")
            
            if item.get('mimeType') == 'application/vnd.google-apps.folder':
                raise GDriveError(f"Cannot download a folder: {drive_path}")
            
            request = self.service.files().get_media(fileId=item['id'])
            
            # Ensure local directory exists
            local_dir = os.path.dirname(local_path)
            if local_dir:
                os.makedirs(local_dir, exist_ok=True)
            
            with open(local_path, 'wb') as f:
                _download_with_retry(request, f)
            
        except GDriveError:
            raise
        except Exception as e:
            raise GDriveError(f"Failed to download file: {str(e)}")

    def delete_item(self, drive_path: str) -> None:
        """Moves a file or folder to Trash (no permanent deletion)."""
        try:
            item = self.get_item_by_path(drive_path)
            if not item:
                raise GDriveError(f"Item not found: {drive_path}")
            
            # Move to trash (not permanent delete)
            _execute_with_retry(self.service.files().update(
                fileId=item['id'],
                body={'trashed': True},
                supportsAllDrives=True,
            ))
            
        except GDriveError:
            raise
        except Exception as e:
            raise GDriveError(f"Failed to delete item: {str(e)}")

    def move_file(self, source_path: str, dest_folder_path: str) -> Dict:
        """Move a file to a different folder.
        
        Args:
            source_path: Path to the file to move (e.g., "Insurance/Chase/doc.pdf")
            dest_folder_path: Path to the destination folder (e.g., "Insurance/Chase Bank")
            
        Returns:
            Updated file metadata
            
        Raises:
            GDriveError: If file not found or move fails
        """
        try:
            # Get the source file
            source_item = self.get_item_by_path(source_path)
            if not source_item:
                raise GDriveError(f"Source file not found: {source_path}")
            
            if source_item.get('mimeType') == 'application/vnd.google-apps.folder':
                raise GDriveError(f"Cannot move a folder with this method: {source_path}")
            
            # Get current parent folder ID
            source_parts = [p for p in source_path.split('/') if p]
            if len(source_parts) > 1:
                source_folder_path = '/'.join(source_parts[:-1])
                old_parent_id = self._get_folder_id(source_folder_path)
            else:
                old_parent_id = self.root_folder_id
            
            # Get destination folder ID
            new_parent_id = self._get_folder_id(dest_folder_path)
            
            # Move the file by updating its parents
            result = _execute_with_retry(self.service.files().update(
                fileId=source_item['id'],
                addParents=new_parent_id,
                removeParents=old_parent_id,
                fields='id, name, mimeType, size, modifiedTime',
                supportsAllDrives=True,
            ))
            
            return result
            
        except GDriveError:
            raise
        except Exception as e:
            raise GDriveError(f"Failed to move file: {str(e)}")

    def read_file_content(self, drive_path: str) -> str:
        """Reads the content of a text file from Google Drive and returns it as a string."""
        try:
            item = self.get_item_by_path(drive_path)
            if not item:
                raise GDriveError(f"File not found: {drive_path}")
            
            if item.get('mimeType') == 'application/vnd.google-apps.folder':
                raise GDriveError(f"Cannot read a folder: {drive_path}")
            
            request = self.service.files().get_media(fileId=item['id'])
            
            buffer = io.BytesIO()
            _download_with_retry(request, buffer)
            buffer.seek(0)
            return buffer.read().decode('utf-8')
            
        except GDriveError:
            raise
        except Exception as e:
            raise GDriveError(f"Failed to read file content: {str(e)}")

    def list_files_recursive(self, folder_id: Optional[str] = None, extension: str = ".pdf") -> List[Dict]:
        """Recursively list all files with given extension in folder and subfolders.
        
        Args:
            folder_id: Starting folder ID. If None, uses root_folder_id.
            extension: File extension to filter by (e.g., ".pdf"). Case-insensitive.
            
        Returns:
            List of dicts with keys: id, name, path (relative path from starting folder)
            
        Raises:
            GDriveError: If folder can't be accessed
        """
        if folder_id is None:
            folder_id = self.root_folder_id
        
        if not folder_id:
            raise GDriveError("No folder ID specified and no root folder set")
        
        extension = extension.lower()
        results = []
        
        def _recurse(current_folder_id: str, current_path: str) -> None:
            """Recursively traverse folders."""
            try:
                page_token = None
                while True:
                    response = _execute_with_retry(self.service.files().list(
                        q=f"'{current_folder_id}' in parents and trashed=false",
                        pageSize=100,
                        fields="nextPageToken, files(id, name, mimeType)",
                        pageToken=page_token,
                        supportsAllDrives=True,
                        includeItemsFromAllDrives=True,
                    ))
                    
                    for item in response.get('files', []):
                        item_path = f"{current_path}/{item['name']}" if current_path else item['name']
                        
                        if item['mimeType'] == 'application/vnd.google-apps.folder':
                            # Recurse into subfolder
                            _recurse(item['id'], item_path)
                        elif item['name'].lower().endswith(extension):
                            # Add matching file
                            results.append({
                                'id': item['id'],
                                'name': item['name'],
                                'path': item_path
                            })
                    
                    page_token = response.get('nextPageToken')
                    if not page_token:
                        break
                        
            except Exception as e:
                raise GDriveError(f"Failed to list files in folder: {str(e)}")
        
        _recurse(folder_id, "")
        return results

    def download_to_temp(self, file_id: str, filename: Optional[str] = None) -> str:
        """Download a file to a temporary location.
        
        Args:
            file_id: Google Drive file ID
            filename: Optional filename for the temp file. If not provided,
                     fetches the original filename from Drive.
                     
        Returns:
            Path to the downloaded temporary file
            
        Raises:
            GDriveError: If download fails
        """
        try:
            # Get file metadata if filename not provided
            if not filename:
                file_meta = _execute_with_retry(self.service.files().get(
                    fileId=file_id,
                    fields="name",
                    supportsAllDrives=True,
                ))
                filename = file_meta['name']
            
            # Create temp file with appropriate extension
            _, ext = os.path.splitext(filename)
            temp_fd, temp_path = tempfile.mkstemp(suffix=ext)
            os.close(temp_fd)
            
            # Download the file
            request = self.service.files().get_media(fileId=file_id)
            
            with open(temp_path, 'wb') as f:
                _download_with_retry(request, f)
            
            return temp_path
            
        except Exception as e:
            raise GDriveError(f"Failed to download file to temp: {str(e)}") 