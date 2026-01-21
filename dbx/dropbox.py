"""Dropbox client for papersort inbox operations.

This module provides read-only access to Dropbox for use as an inbox source.
It supports OAuth 2.0 authentication with refresh tokens for persistent access.

Usage:
    # One-time authentication (opens browser)
    authenticate_dropbox("app_key", "app_secret", "dropbox_token.json")
    
    # Normal usage
    dbx = Dropbox(token_file="dropbox_token.json")
    files = dbx.list_files_recursive("/Inbox", extension=".pdf")
    temp_path = dbx.download_to_temp("/Inbox/document.pdf")
"""

from typing import List, Dict, Optional
import dropbox as dropbox_sdk
from dropbox.exceptions import ApiError, AuthError
from dropbox.files import FileMetadata, FolderMetadata
import json
import os
import tempfile
import webbrowser

from utils.retry import (
    retry_on_transient_error,
    is_transient_network_error,
)


class DropboxError(Exception):
    """Base exception for Dropbox operations."""
    pass


# ---------------------------------------------------------------------------
# Dropbox Retry Configuration
# ---------------------------------------------------------------------------

# HTTP status codes that indicate transient errors worth retrying
TRANSIENT_HTTP_STATUS_CODES = {429, 500, 502, 503, 504}


def _is_retryable_dropbox_error(exc: Exception) -> bool:
    """
    Determine if a Dropbox API error should be retried.
    
    We retry on:
    - Rate limiting (429)
    - Server errors (5xx)
    - Network errors (connection reset, timeout, etc.)
    
    We do NOT retry on:
    - Auth errors (invalid token, expired, etc.)
    - Path errors (not found, invalid path, etc.)
    - Other client errors
    """
    if isinstance(exc, AuthError):
        # Auth errors won't be fixed by retrying
        return False
    
    if isinstance(exc, ApiError):
        # ApiError can wrap HTTP errors - check if it's a rate limit
        if exc.error.is_rate_limit_error():
            return True
        # Other API errors (path not found, etc.) shouldn't be retried
        return False
    
    # Check for general network errors
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
    """
    Perform OAuth 2.0 authentication flow for Dropbox.
    
    This opens a browser for the user to authorize the app, then saves
    the refresh token to a file for future use.
    
    Args:
        app_key: Dropbox app key from the App Console
        app_secret: Dropbox app secret from the App Console
        token_file: Path to save the token JSON file
        
    Returns:
        True if authentication succeeded, False otherwise
    """
    # Create OAuth flow with PKCE
    auth_flow = dropbox_sdk.DropboxOAuth2FlowNoRedirect(
        app_key,
        app_secret,
        token_access_type='offline',  # Request refresh token
        use_pkce=True,
    )
    
    # Get authorization URL
    authorize_url = auth_flow.start()
    
    print("\n=== Dropbox Authorization ===")
    print("1. Opening browser for authorization...")
    print(f"   URL: {authorize_url}")
    print()
    
    # Try to open browser automatically
    webbrowser.open(authorize_url)
    
    print("2. After authorizing, copy the authorization code from the page.")
    auth_code = input("3. Enter the authorization code here: ").strip()
    
    if not auth_code:
        print("Error: No authorization code provided")
        return False
    
    try:
        # Exchange auth code for tokens
        oauth_result = auth_flow.finish(auth_code)
        
        # Save tokens to file
        token_data = {
            "app_key": app_key,
            "app_secret": app_secret,
            "refresh_token": oauth_result.refresh_token,
        }
        
        with open(token_file, 'w') as f:
            json.dump(token_data, f, indent=2)
        
        # Set restrictive permissions on token file
        os.chmod(token_file, 0o600)
        
        print(f"\nSuccess! Token saved to {token_file}")
        print("You can now use Dropbox as an inbox source.")
        return True
        
    except Exception as e:
        print(f"\nError during authentication: {str(e)}")
        return False


# ---------------------------------------------------------------------------
# Dropbox Client Class
# ---------------------------------------------------------------------------

class Dropbox:
    """
    Dropbox client for inbox operations (read-only).
    
    This class provides methods to list and download files from Dropbox,
    designed to be used as an inbox source for papersort.
    """
    
    def __init__(self, token_file: str = "dropbox_token.json") -> None:
        """
        Initialize Dropbox client.
        
        Args:
            token_file: Path to the token JSON file (created by authenticate_dropbox)
            
        Raises:
            DropboxError: If token file not found or invalid
        """
        self.token_file = token_file
        self.client = None
        
        if not os.path.exists(token_file):
            raise DropboxError(
                f"Token file not found: {token_file}\n"
                "Run 'python papersort.py --auth-dropbox' to authenticate."
            )
        
        try:
            with open(token_file, 'r') as f:
                token_data = json.load(f)
        except json.JSONDecodeError as e:
            raise DropboxError(f"Invalid token file: {str(e)}")
        
        required_keys = ['app_key', 'app_secret', 'refresh_token']
        for key in required_keys:
            if key not in token_data:
                raise DropboxError(f"Token file missing required key: {key}")
        
        # Create client with refresh token (auto-refreshes access token)
        self.client = dropbox_sdk.Dropbox(
            app_key=token_data['app_key'],
            app_secret=token_data['app_secret'],
            oauth2_refresh_token=token_data['refresh_token'],
        )
        
        # Verify connection works
        try:
            self._get_account_info()
        except AuthError as e:
            raise DropboxError(
                f"Authentication failed: {str(e)}\n"
                "Your token may have been revoked. Run 'python papersort.py --auth-dropbox' to re-authenticate."
            )
    
    @_with_retry
    def _get_account_info(self) -> dict:
        """Get current account info (also verifies auth works)."""
        account = self.client.users_get_current_account()
        return {
            'name': account.name.display_name,
            'email': account.email,
        }
    
    def get_display_name(self) -> str:
        """Get a display name for this Dropbox account."""
        try:
            info = self._get_account_info()
            return info['name']
        except Exception:
            return "Dropbox"
    
    @_with_retry
    def _list_folder(self, path: str, cursor: Optional[str] = None) -> tuple:
        """
        List folder contents with pagination support.
        
        Args:
            path: Dropbox path (use "" for root)
            cursor: Pagination cursor from previous call
            
        Returns:
            Tuple of (entries, cursor, has_more)
        """
        if cursor:
            result = self.client.files_list_folder_continue(cursor)
        else:
            # Dropbox uses "" for root, not "/"
            if path == "/":
                path = ""
            result = self.client.files_list_folder(path)
        
        return (result.entries, result.cursor, result.has_more)
    
    def list_files_recursive(self, folder_path: str = "", 
                             extension: str = ".pdf") -> List[Dict]:
        """
        Recursively list all files with given extension in folder and subfolders.
        
        Args:
            folder_path: Starting folder path (e.g., "/Inbox" or "" for root)
            extension: File extension to filter by (e.g., ".pdf"). Case-insensitive.
            
        Returns:
            List of dicts with keys: path, name, id, size, modified
            
        Raises:
            DropboxError: If folder can't be accessed
        """
        # Normalize path
        if folder_path and not folder_path.startswith("/"):
            folder_path = "/" + folder_path
        if folder_path == "/":
            folder_path = ""
        
        extension = extension.lower()
        results = []
        folders_to_process = [folder_path]
        
        while folders_to_process:
            current_folder = folders_to_process.pop(0)
            
            try:
                cursor = None
                has_more = True
                
                while has_more:
                    entries, cursor, has_more = self._list_folder(current_folder, cursor)
                    
                    for entry in entries:
                        if isinstance(entry, FolderMetadata):
                            # Add subfolder to processing queue
                            folders_to_process.append(entry.path_display)
                        elif isinstance(entry, FileMetadata):
                            # Check extension
                            if entry.name.lower().endswith(extension):
                                results.append({
                                    'path': entry.path_display,
                                    'name': entry.name,
                                    'id': entry.id,
                                    'size': entry.size,
                                    'modified': entry.server_modified.isoformat(),
                                })
                                
            except ApiError as e:
                if e.error.is_path() and e.error.get_path().is_not_found():
                    raise DropboxError(f"Folder not found: {current_folder}")
                raise DropboxError(f"Failed to list folder {current_folder}: {str(e)}")
            except Exception as e:
                raise DropboxError(f"Failed to list folder {current_folder}: {str(e)}")
        
        return results
    
    @_with_retry
    def _download_file(self, path: str, local_path: str) -> None:
        """Download a file to a local path."""
        self.client.files_download_to_file(local_path, path)
    
    def download_to_temp(self, file_path: str, filename: Optional[str] = None) -> str:
        """
        Download a file to a temporary location.
        
        Args:
            file_path: Dropbox file path (e.g., "/Inbox/document.pdf")
            filename: Optional filename for the temp file. If not provided,
                     uses the original filename.
                     
        Returns:
            Path to the downloaded temporary file
            
        Raises:
            DropboxError: If download fails
        """
        if not filename:
            filename = os.path.basename(file_path)
        
        # Create temp file with appropriate extension
        _, ext = os.path.splitext(filename)
        temp_fd, temp_path = tempfile.mkstemp(suffix=ext)
        os.close(temp_fd)
        
        try:
            self._download_file(file_path, temp_path)
            return temp_path
        except ApiError as e:
            # Clean up temp file on error
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            
            if e.error.is_path() and e.error.get_path().is_not_found():
                raise DropboxError(f"File not found: {file_path}")
            raise DropboxError(f"Failed to download {file_path}: {str(e)}")
        except Exception as e:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            raise DropboxError(f"Failed to download {file_path}: {str(e)}")
