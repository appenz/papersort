"""Smoke tests for GDriveDriver.

These tests require:
1. A service_account_key.json file in project root
2. GDRIVE_TEST_FOLDER_ID environment variable pointing to a test folder

Tests are skipped if credentials are not available.
"""

import os
import tempfile
import pytest

# Skip all tests if no credentials
pytestmark = pytest.mark.skipif(
    not os.path.exists("service_account_key.json"),
    reason="No service_account_key.json found"
)


@pytest.fixture
def test_folder_id():
    """Get test folder ID from environment."""
    folder_id = os.environ.get("GDRIVE_TEST_FOLDER_ID")
    if not folder_id:
        pytest.skip("GDRIVE_TEST_FOLDER_ID not set")
    return folder_id


@pytest.fixture
def driver(test_folder_id):
    """Create a GDriveDriver instance."""
    from storage import GDriveDriver
    return GDriveDriver(test_folder_id)


class TestGDriveSmoke:
    """Simple smoke tests - one call per operation."""
    
    def test_display_name(self, driver):
        """Verify we can connect and get folder name."""
        assert "Google Drive" in driver.display_name
    
    def test_list_files(self, driver):
        """Verify list_files returns a list."""
        files = driver.list_files()
        assert isinstance(files, list)
    
    def test_list_folders(self, driver):
        """Verify list_folders returns a list."""
        folders = driver.list_folders()
        assert isinstance(folders, list)
    
    def test_file_exists(self, driver):
        """Verify file_exists works for non-existent file."""
        # Should return False for non-existent file
        assert driver.file_exists("nonexistent_file_12345.pdf") is False
    
    def test_read_text_layout(self, driver):
        """Verify we can read layout.txt if it exists."""
        if driver.file_exists("layout.txt"):
            content = driver.read_text("layout.txt")
            assert isinstance(content, str)
            assert len(content) > 0
    
    def test_sanitize_filename(self, driver):
        """Verify sanitize_filename."""
        assert driver.sanitize_filename("test/name") == "test-name"
        assert driver.sanitize_filename("E*Trade") == "E*Trade"  # Allowed on GDrive
    
    def test_upload_and_delete(self, driver):
        """Verify upload and delete cycle."""
        # Create temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("test content")
            temp_path = f.name
        
        try:
            test_filename = "_papersort_test_upload.txt"
            
            # Upload
            driver.upload(temp_path, test_filename)
            assert driver.file_exists(test_filename)
            
            # Delete (moves to trash)
            driver.delete(test_filename)
            
        finally:
            os.unlink(temp_path)
