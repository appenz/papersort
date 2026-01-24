"""Dropbox storage driver (read-only).

This module provides read-only access to Dropbox for use as an inbox source.
It supports OAuth 2.0 authentication with refresh tokens for persistent access.
"""

from typing import List, Optional
import dropbox as dropbox_sdk
from dropbox.exceptions import ApiError, AuthError
from dropbox.files import FileMetadata, FolderMetadata
import json
import os
import tempfile
import webbrowser

from .base import StorageDriver, StorageError, FileInfo, FolderInfo
from utils.retry import retry_on_transient_error, is_transient_network_error


# ---------------------------------------------------------------------------
# Dropbox Retry Configuration
# ---------------------------------------------------------------------------

def _is_retryable_dropbox_error(exc: Exception) -> bool:
    """Determine if a Dropbox API error should be retried."""
    if isinstance(exc, AuthError):
        return False
    if isinstance(exc, ApiError):
        if exc.error.is_rate_limit_error():
            return True
        return False
    return is_transient_network_error(exc)


def _log_retry(exc: Exception, attempt: int, delay: float) -> None:
    """Log when a retry is about to happen."""
    error_desc = type(exc).__name__
    print(f"  [Retry] {error_desc} on attempt {attempt}, retrying in {delay:.1f}s...")


def _with_retry(func):
    """Decorator to add retry logic to Dropbox API calls."""
    @retry_on_transient_error(
        is_retryable=_is_retryable_dropbox_error,
        max_retries=5,
        base_delay=1.0,
        max_delay=60.0,
        on_retry=_log_retry,
    )
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def authenticate_dropbox(app_key: str, app_secret: str, 
                         token_file: str = "dropbox_token.json") -> bool:
    """Perform OAuth 2.0 authentication flow for Dropbox.
    
    This opens a browser for the user to authorize the app, then saves
    the refresh token to a file for future use.
    
    Args:
        app_key: Dropbox app key from the App Console
        app_secret: Dropbox app secret from the App Console
        token_file: Path to save the token JSON file
        
    Returns:
        True if authentication succeeded, False otherwise
    """
    auth_flow = dropbox_sdk.DropboxOAuth2FlowNoRedirect(
        app_key,
        app_secret,
        token_access_type='offline',
        use_pkce=True,
    )
    
    authorize_url = auth_flow.start()
    
    print("\n=== Dropbox Authorization ===")
    print("1. Opening browser for authorization...")
    print(f"   URL: {authorize_url}")
    print()
    
    webbrowser.open(authorize_url)
    
    print("2. After authorizing, copy the authorization code from the page.")
    auth_code = input("3. Enter the authorization code here: ").strip()
    
    if not auth_code:
        print("Error: No authorization code provided")
        return False
    
    try:
        oauth_result = auth_flow.finish(auth_code)
        
        token_data = {
            "app_key": app_key,
            "app_secret": app_secret,
            "refresh_token": oauth_result.refresh_token,
        }
        
        with open(token_file, 'w') as f:
            json.dump(token_data, f, indent=2)
        
        os.chmod(token_file, 0o600)
        
        print(f"\nSuccess! Token saved to {token_file}")
        print("You can now use Dropbox as an inbox source.")
        return True
        
    except Exception as e:
        print(f"\nError during authentication: {str(e)}")
        return False


# ---------------------------------------------------------------------------
# Dropbox Driver
# ---------------------------------------------------------------------------

class DropboxDriver(StorageDriver):
    """Storage driver for Dropbox.
    
    Supports read operations and delete for inbox cleanup.
    """
    
    def __init__(self, root_path: str = "",
                 token_file: str = "dropbox_token.json") -> None:
        """Initialize Dropbox storage driver.
        
        Credentials are loaded from:
        1. Token file (dropbox_token.json) if it exists
        2. DROPBOX_TOKEN_JSON environment variable (for Docker deployment)
        
        Args:
            root_path: Root path within Dropbox (e.g., "/Inbox")
            token_file: Path to the token JSON file
            
        Raises:
            StorageError: If authentication fails
        """
        # Normalize root path
        if root_path and not root_path.startswith("/"):
            root_path = "/" + root_path
        if root_path == "/":
            root_path = ""
        self.root_path = root_path
        
        self._account_name: Optional[str] = None
        
        # Try to load credentials from file first, then env var
        token_data = None
        
        if os.path.exists(token_file):
            try:
                with open(token_file, 'r') as f:
                    token_data = json.load(f)
            except json.JSONDecodeError as e:
                raise StorageError(f"Invalid token file: {e}")
        elif os.environ.get('DROPBOX_TOKEN_JSON'):
            try:
                token_data = json.loads(os.environ['DROPBOX_TOKEN_JSON'])
            except json.JSONDecodeError as e:
                raise StorageError(f"Invalid DROPBOX_TOKEN_JSON env var: {e}")
        else:
            raise StorageError(
                f"No Dropbox credentials found.\n"
                f"Either create {token_file} (run 'python main.py --auth-dropbox')\n"
                "or set DROPBOX_TOKEN_JSON environment variable."
            )
        
        required_keys = ['app_key', 'app_secret', 'refresh_token']
        for key in required_keys:
            if key not in token_data:
                raise StorageError(f"Dropbox credentials missing required key: {key}")
        
        self.client = dropbox_sdk.Dropbox(
            app_key=token_data['app_key'],
            app_secret=token_data['app_secret'],
            oauth2_refresh_token=token_data['refresh_token'],
        )
        
        # Verify connection
        try:
            account = self._get_account_info()
            self._account_name = account['name']
        except AuthError as e:
            raise StorageError(
                f"Authentication failed: {e}\n"
                "Run 'python main.py --auth-dropbox' to re-authenticate."
            )
    
    @_with_retry
    def _get_account_info(self) -> dict:
        """Get current account info."""
        account = self.client.users_get_current_account()
        return {
            'name': account.name.display_name,
            'email': account.email,
        }
    
    @property
    def display_name(self) -> str:
        path_display = self.root_path or "/"
        account = self._account_name or "Dropbox"
        return f"{path_display} ({account} Dropbox)"
    
    def _full_path(self, path: str) -> str:
        """Convert relative path to full Dropbox path."""
        if not path:
            return self.root_path
        if self.root_path:
            return f"{self.root_path}/{path}"
        return f"/{path}" if not path.startswith("/") else path
    
    @_with_retry
    def _list_folder(self, path: str, cursor: Optional[str] = None) -> tuple:
        """List folder contents with pagination support."""
        if cursor:
            result = self.client.files_list_folder_continue(cursor)
        else:
            # Dropbox uses "" for root
            dbx_path = path if path else ""
            result = self.client.files_list_folder(dbx_path)
        return (result.entries, result.cursor, result.has_more)
    
    def list_files(self, path: str = "", recursive: bool = False,
                   extension: Optional[str] = None) -> List[FileInfo]:
        """List files at the given path."""
        full_path = self._full_path(path)
        extension_lower = extension.lower() if extension else None
        results = []
        
        if recursive:
            folders_to_process = [full_path]
            
            while folders_to_process:
                current_folder = folders_to_process.pop(0)
                
                try:
                    cursor = None
                    has_more = True
                    
                    while has_more:
                        entries, cursor, has_more = self._list_folder(current_folder, cursor)
                        
                        for entry in entries:
                            if isinstance(entry, FolderMetadata):
                                folders_to_process.append(entry.path_display)
                            elif isinstance(entry, FileMetadata):
                                if extension_lower and not entry.name.lower().endswith(extension_lower):
                                    continue
                                
                                # Convert to relative path
                                rel_path = entry.path_display
                                if self.root_path and rel_path.startswith(self.root_path):
                                    rel_path = rel_path[len(self.root_path):].lstrip('/')
                                
                                results.append(FileInfo(
                                    path=rel_path,
                                    name=entry.name,
                                    size=entry.size,
                                    id=entry.id
                                ))
                                
                except ApiError as e:
                    if e.error.is_path() and e.error.get_path().is_not_found():
                        raise StorageError(f"Folder not found: {path}")
                    raise StorageError(f"Failed to list folder: {e}")
        else:
            try:
                cursor = None
                has_more = True
                
                while has_more:
                    entries, cursor, has_more = self._list_folder(full_path, cursor)
                    
                    for entry in entries:
                        if isinstance(entry, FileMetadata):
                            if extension_lower and not entry.name.lower().endswith(extension_lower):
                                continue
                            
                            rel_path = entry.path_display
                            if self.root_path and rel_path.startswith(self.root_path):
                                rel_path = rel_path[len(self.root_path):].lstrip('/')
                            
                            results.append(FileInfo(
                                path=rel_path,
                                name=entry.name,
                                size=entry.size,
                                id=entry.id
                            ))
                            
            except ApiError as e:
                if e.error.is_path() and e.error.get_path().is_not_found():
                    raise StorageError(f"Folder not found: {path}")
                raise StorageError(f"Failed to list folder: {e}")
        
        return results
    
    def list_folders(self, path: str = "") -> List[FolderInfo]:
        """List immediate subfolders at the given path."""
        full_path = self._full_path(path)
        results = []
        
        try:
            cursor = None
            has_more = True
            
            while has_more:
                entries, cursor, has_more = self._list_folder(full_path, cursor)
                
                for entry in entries:
                    if isinstance(entry, FolderMetadata):
                        rel_path = entry.path_display
                        if self.root_path and rel_path.startswith(self.root_path):
                            rel_path = rel_path[len(self.root_path):].lstrip('/')
                        
                        results.append(FolderInfo(
                            path=rel_path,
                            name=entry.name,
                            id=entry.id
                        ))
                        
        except ApiError as e:
            if e.error.is_path() and e.error.get_path().is_not_found():
                raise StorageError(f"Folder not found: {path}")
            raise StorageError(f"Failed to list folder: {e}")
        
        return results
    
    def file_exists(self, path: str) -> bool:
        """Check if a file exists at the given path."""
        full_path = self._full_path(path)
        
        try:
            metadata = self.client.files_get_metadata(full_path)
            return isinstance(metadata, FileMetadata)
        except ApiError:
            return False
    
    def read_text(self, path: str) -> str:
        """Read a text file and return its contents."""
        full_path = self._full_path(path)
        
        try:
            _, response = self.client.files_download(full_path)
            return response.content.decode('utf-8')
        except ApiError as e:
            if e.error.is_path() and e.error.get_path().is_not_found():
                raise StorageError(f"File not found: {path}")
            raise StorageError(f"Failed to read file: {e}")
    
    @_with_retry
    def _download_file(self, path: str, local_path: str) -> None:
        """Download a file to a local path."""
        self.client.files_download_to_file(local_path, path)
    
    def download_to_temp(self, path: str) -> str:
        """Download a file to a temporary location."""
        full_path = self._full_path(path)
        filename = os.path.basename(path)
        
        _, ext = os.path.splitext(filename)
        temp_fd, temp_path = tempfile.mkstemp(suffix=ext)
        os.close(temp_fd)
        
        try:
            self._download_file(full_path, temp_path)
            return temp_path
        except ApiError as e:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            
            if e.error.is_path() and e.error.get_path().is_not_found():
                raise StorageError(f"File not found: {path}")
            raise StorageError(f"Failed to download file: {e}")
        except Exception as e:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise StorageError(f"Failed to download file: {e}")
    
    def sanitize_filename(self, name: str) -> str:
        """Sanitize a filename for Dropbox.
        
        Dropbox is fairly permissive - mainly / is forbidden.
        """
        name = name.replace('/', '-')
        name = name.strip()
        return name
    
    @_with_retry
    def delete(self, path: str) -> None:
        """Delete a file or folder from Dropbox.
        
        Args:
            path: Relative path to the file or folder to delete
            
        Raises:
            StorageError: If delete fails or path not found
        """
        full_path = self._full_path(path)
        
        try:
            self.client.files_delete_v2(full_path)
        except ApiError as e:
            if e.error.is_path_lookup() and e.error.get_path_lookup().is_not_found():
                raise StorageError(f"File not found: {path}")
            raise StorageError(f"Failed to delete file: {e}")
    
    # =========================================================================
    # Legacy compatibility methods
    # =========================================================================
    
    def get_display_name(self) -> str:
        """Legacy method for backward compatibility."""
        return self._account_name or "Dropbox"
    
    def list_files_recursive(self, folder_path: str = "",
                             extension: str = ".pdf") -> List[dict]:
        """Legacy method for backward compatibility."""
        files = self.list_files(path=folder_path, recursive=True, extension=extension)
        
        # Convert to legacy format with full paths
        return [{
            'path': f.path if self.root_path == "" else f"{self.root_path}/{f.path}",
            'name': f.name,
            'id': f.id,
            'size': f.size,
        } for f in files]
    
    def download_to_temp_legacy(self, file_path: str, filename: Optional[str] = None) -> str:
        """Legacy method - accepts full path instead of relative."""
        # Strip root_path if present to get relative path
        rel_path = file_path
        if self.root_path and file_path.startswith(self.root_path):
            rel_path = file_path[len(self.root_path):].lstrip('/')
        return self.download_to_temp(rel_path)
