"""Local filesystem storage driver."""

import os
import re
import shutil
from typing import List, Optional

from .base import StorageDriver, StorageError, FileInfo, FolderInfo


class LocalDriver(StorageDriver):
    """Storage driver for local filesystem.
    
    All paths are relative to the root_path provided at construction.
    """
    
    def __init__(self, root_path: str) -> None:
        """Initialize local storage driver.
        
        Args:
            root_path: Absolute path to the root directory
            
        Raises:
            StorageError: If root_path doesn't exist
        """
        self.root_path = os.path.abspath(root_path)
        if not os.path.exists(self.root_path):
            raise StorageError(f"Directory does not exist: {self.root_path}")
        if not os.path.isdir(self.root_path):
            raise StorageError(f"Not a directory: {self.root_path}")
    
    @property
    def display_name(self) -> str:
        return f"{self.root_path} (local)"
    
    def _full_path(self, path: str) -> str:
        """Convert relative path to absolute path."""
        if not path:
            return self.root_path
        return os.path.join(self.root_path, path)
    
    def list_files(self, path: str = "", recursive: bool = False,
                   extension: Optional[str] = None) -> List[FileInfo]:
        """List files at the given path."""
        full_path = self._full_path(path)
        
        if not os.path.exists(full_path):
            raise StorageError(f"Path does not exist: {path}")
        if not os.path.isdir(full_path):
            raise StorageError(f"Not a directory: {path}")
        
        extension_lower = extension.lower() if extension else None
        results = []
        
        if recursive:
            for root, dirs, files in os.walk(full_path):
                for filename in files:
                    if extension_lower and not filename.lower().endswith(extension_lower):
                        continue
                    
                    abs_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(abs_path, self.root_path)
                    
                    try:
                        size = os.path.getsize(abs_path)
                    except OSError:
                        size = None
                    
                    results.append(FileInfo(
                        path=rel_path,
                        name=filename,
                        size=size
                    ))
        else:
            for filename in os.listdir(full_path):
                abs_path = os.path.join(full_path, filename)
                if not os.path.isfile(abs_path):
                    continue
                if extension_lower and not filename.lower().endswith(extension_lower):
                    continue
                
                rel_path = os.path.relpath(abs_path, self.root_path)
                
                try:
                    size = os.path.getsize(abs_path)
                except OSError:
                    size = None
                
                results.append(FileInfo(
                    path=rel_path,
                    name=filename,
                    size=size
                ))
        
        return results
    
    def list_folders(self, path: str = "") -> List[FolderInfo]:
        """List immediate subfolders at the given path."""
        full_path = self._full_path(path)
        
        if not os.path.exists(full_path):
            raise StorageError(f"Path does not exist: {path}")
        if not os.path.isdir(full_path):
            raise StorageError(f"Not a directory: {path}")
        
        results = []
        for name in os.listdir(full_path):
            abs_path = os.path.join(full_path, name)
            if os.path.isdir(abs_path):
                rel_path = os.path.relpath(abs_path, self.root_path)
                results.append(FolderInfo(
                    path=rel_path,
                    name=name
                ))
        
        return results
    
    def file_exists(self, path: str) -> bool:
        """Check if a file exists at the given path."""
        full_path = self._full_path(path)
        return os.path.isfile(full_path)
    
    def read_text(self, path: str) -> str:
        """Read a text file and return its contents."""
        full_path = self._full_path(path)
        
        if not os.path.exists(full_path):
            raise StorageError(f"File does not exist: {path}")
        if not os.path.isfile(full_path):
            raise StorageError(f"Not a file: {path}")
        
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            raise StorageError(f"Failed to read file {path}: {e}")
    
    def download_to_temp(self, path: str) -> str:
        """Return the local path directly (no temp copy needed).
        
        For local storage, we return the original path since it's already
        on the local filesystem. The caller should NOT delete this file.
        """
        full_path = self._full_path(path)
        
        if not os.path.exists(full_path):
            raise StorageError(f"File does not exist: {path}")
        if not os.path.isfile(full_path):
            raise StorageError(f"Not a file: {path}")
        
        return full_path
    
    def upload(self, local_path: str, dest_path: str) -> None:
        """Copy a local file to the storage location."""
        full_dest = self._full_path(dest_path)
        
        # Create parent directories
        dest_dir = os.path.dirname(full_dest)
        if dest_dir:
            os.makedirs(dest_dir, exist_ok=True)
        
        try:
            shutil.copy2(local_path, full_dest)
        except Exception as e:
            raise StorageError(f"Failed to copy file to {dest_path}: {e}")
    
    def move(self, src_path: str, dest_folder: str) -> None:
        """Move a file to a different folder."""
        full_src = self._full_path(src_path)
        
        if not os.path.exists(full_src):
            raise StorageError(f"Source file does not exist: {src_path}")
        
        filename = os.path.basename(src_path)
        dest_path = os.path.join(dest_folder, filename) if dest_folder else filename
        full_dest = self._full_path(dest_path)
        
        # Create parent directories
        dest_dir = os.path.dirname(full_dest)
        if dest_dir:
            os.makedirs(dest_dir, exist_ok=True)
        
        try:
            shutil.move(full_src, full_dest)
        except Exception as e:
            raise StorageError(f"Failed to move file from {src_path} to {dest_path}: {e}")
    
    def delete(self, path: str) -> None:
        """Delete a file or folder."""
        full_path = self._full_path(path)
        
        if not os.path.exists(full_path):
            raise StorageError(f"Path does not exist: {path}")
        
        try:
            if os.path.isfile(full_path):
                os.remove(full_path)
            else:
                shutil.rmtree(full_path)
        except Exception as e:
            raise StorageError(f"Failed to delete {path}: {e}")
    
    def sanitize_filename(self, name: str) -> str:
        """Sanitize a filename for local filesystem.
        
        Removes characters that are invalid on most filesystems:
        / \\ : * ? \" < > |
        """
        # Replace problematic characters with safe alternatives
        name = name.replace('/', '-')
        name = name.replace('\\', '-')
        name = name.replace(':', '-')
        name = name.replace('*', '')
        name = name.replace('?', '')
        name = name.replace('"', "'")
        name = name.replace('<', '')
        name = name.replace('>', '')
        name = name.replace('|', '-')
        
        # Remove leading/trailing whitespace and dots
        name = name.strip().strip('.')
        
        # Collapse multiple spaces/dashes
        name = re.sub(r'\s+', ' ', name)
        name = re.sub(r'-+', '-', name)
        
        # Limit length (leave room for extensions)
        if len(name) > 100:
            name = name[:100].strip()
        
        return name
