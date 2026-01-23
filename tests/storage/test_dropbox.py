"""Smoke tests for DropboxDriver.

These tests require:
1. A dropbox_token.json file in project root

Tests are skipped if credentials are not available.
Only tests reading root folder since Dropbox driver is read-only.
"""

import os
import pytest

# Skip all tests if no credentials
pytestmark = pytest.mark.skipif(
    not os.path.exists("dropbox_token.json"),
    reason="No dropbox_token.json found"
)


@pytest.fixture
def driver():
    """Create a DropboxDriver instance for root."""
    from storage import DropboxDriver
    return DropboxDriver(root_path="")


class TestDropboxSmoke:
    """Simple smoke tests - read operations only."""
    
    def test_display_name(self, driver):
        """Verify we can connect and get account name."""
        assert "Dropbox" in driver.display_name
    
    def test_list_files_root(self, driver):
        """Verify we can list files in root."""
        files = driver.list_files()
        assert isinstance(files, list)
        # Root should have something
        # (won't assert content since we don't know what's there)
    
    def test_list_folders_root(self, driver):
        """Verify we can list folders in root."""
        folders = driver.list_folders()
        assert isinstance(folders, list)
    
    def test_file_exists(self, driver):
        """Verify file_exists returns False for non-existent."""
        assert driver.file_exists("nonexistent_file_12345.pdf") is False
    
    def test_sanitize_filename(self, driver):
        """Verify sanitize_filename."""
        assert driver.sanitize_filename("test/name") == "test-name"
        assert driver.sanitize_filename("  trimmed  ") == "trimmed"
    
    def test_upload_raises_not_implemented(self, driver):
        """Verify write operations raise NotImplementedError."""
        with pytest.raises(NotImplementedError):
            driver.upload("/tmp/test.txt", "test.txt")
    
    def test_delete_raises_not_implemented(self, driver):
        """Verify delete raises NotImplementedError."""
        with pytest.raises(NotImplementedError):
            driver.delete("test.txt")
