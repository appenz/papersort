"""
Unit tests for GDrive class.
Tests run against the /appenz_test folder and clean up when done.
Tests are skipped if credentials are not present.
"""
import pytest
import os
import tempfile
from gdrive.gdrive import GDrive, GDriveError

# Test folder to use (all tests create/cleanup within this folder)
TEST_ROOT = "appenz_test"


@pytest.fixture(scope="module")
def drive():
    """Create a GDrive instance for testing, skip if no credentials."""
    try:
        d = GDrive()
        # Ensure test root folder exists
        d.create_folder("", TEST_ROOT)
        yield d
    except Exception as e:
        pytest.skip(f"Skipping tests - no credentials available: {str(e)}")


@pytest.fixture(autouse=True)
def cleanup(drive):
    """Clean up test files after each test."""
    yield
    # Clean up any test artifacts in TEST_ROOT
    try:
        items = drive.list_items(TEST_ROOT)
        for item in items:
            try:
                drive.delete_item(f"{TEST_ROOT}/{item['name']}")
            except GDriveError:
                pass
    except GDriveError:
        pass


class TestGDriveInit:
    def test_initialization(self, drive):
        """Test GDrive initializes with valid service."""
        assert drive.service is not None
        assert drive.creds is not None

    def test_docstore_folder_created(self, drive):
        """Test docstore folder is created on init."""
        assert drive.docstore_folder is not None
        assert 'id' in drive.docstore_folder
        assert 'name' in drive.docstore_folder


class TestCreateFolder:
    def test_create_folder(self, drive):
        """Test creating a simple folder."""
        folder = drive.create_folder(TEST_ROOT, "TestFolder")
        assert folder['name'] == "TestFolder"
        assert 'id' in folder

    def test_create_nested_folders(self, drive):
        """Test creating nested folders recursively."""
        folder = drive.create_folder(f"{TEST_ROOT}/Parent/Child", "DeepFolder")
        assert folder['name'] == "DeepFolder"
        assert 'id' in folder

    def test_create_existing_folder_no_duplicate(self, drive):
        """Test that creating existing folder returns it without duplication."""
        folder1 = drive.create_folder(TEST_ROOT, "ExistingFolder")
        folder2 = drive.create_folder(TEST_ROOT, "ExistingFolder")
        assert folder1['id'] == folder2['id']


class TestListItems:
    def test_list_items_empty_folder(self, drive):
        """Test listing items in an empty folder."""
        drive.create_folder(TEST_ROOT, "EmptyFolder")
        items = drive.list_items(f"{TEST_ROOT}/EmptyFolder")
        assert isinstance(items, list)
        assert len(items) == 0

    def test_list_items_with_contents(self, drive):
        """Test listing items returns correct metadata."""
        drive.create_folder(TEST_ROOT, "ListTest")
        drive.create_folder(f"{TEST_ROOT}/ListTest", "SubFolder")
        
        items = drive.list_items(f"{TEST_ROOT}/ListTest")
        assert len(items) == 1
        item = items[0]
        assert item['name'] == "SubFolder"
        assert 'id' in item
        assert 'mimeType' in item


class TestGetItemByPath:
    def test_get_existing_folder(self, drive):
        """Test getting metadata for an existing folder."""
        drive.create_folder(TEST_ROOT, "GetTest")
        item = drive.get_item_by_path(f"{TEST_ROOT}/GetTest")
        assert item is not None
        assert item['name'] == "GetTest"
        assert item['mimeType'] == 'application/vnd.google-apps.folder'

    def test_get_nonexistent_item(self, drive):
        """Test getting metadata for non-existent item returns None."""
        item = drive.get_item_by_path(f"{TEST_ROOT}/NonExistent12345")
        assert item is None

    def test_get_empty_path(self, drive):
        """Test empty path returns None."""
        item = drive.get_item_by_path("")
        assert item is None


class TestUploadFile:
    def test_upload_file(self, drive):
        """Test uploading a file."""
        drive.create_folder(TEST_ROOT, "UploadTest")
        
        # Create a temp file to upload
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Test content for upload")
            temp_path = f.name
        
        try:
            result = drive.upload_file(temp_path, f"{TEST_ROOT}/UploadTest/test.txt")
            assert result['name'] == "test.txt"
            assert 'id' in result
        finally:
            os.unlink(temp_path)

    def test_upload_file_update_existing(self, drive):
        """Test uploading to existing path updates the file."""
        drive.create_folder(TEST_ROOT, "UpdateTest")
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Original content")
            temp_path = f.name
        
        try:
            result1 = drive.upload_file(temp_path, f"{TEST_ROOT}/UpdateTest/update.txt")
            
            # Write new content and upload again
            with open(temp_path, 'w') as f:
                f.write("Updated content")
            
            result2 = drive.upload_file(temp_path, f"{TEST_ROOT}/UpdateTest/update.txt")
            
            # Should be same file ID (updated, not duplicated)
            assert result1['id'] == result2['id']
        finally:
            os.unlink(temp_path)


class TestDownloadFile:
    def test_download_file(self, drive):
        """Test downloading a file."""
        drive.create_folder(TEST_ROOT, "DownloadTest")
        
        # Upload a file first
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Download test content")
            upload_path = f.name
        
        try:
            drive.upload_file(upload_path, f"{TEST_ROOT}/DownloadTest/download.txt")
            
            # Download it
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                download_path = f.name
            
            drive.download_file(f"{TEST_ROOT}/DownloadTest/download.txt", download_path)
            
            with open(download_path, 'r') as f:
                content = f.read()
            assert content == "Download test content"
            
            os.unlink(download_path)
        finally:
            os.unlink(upload_path)

    def test_download_nonexistent_file(self, drive):
        """Test downloading non-existent file raises error."""
        with pytest.raises(GDriveError):
            drive.download_file(f"{TEST_ROOT}/NonExistent.txt", "/tmp/test.txt")


class TestDeleteItem:
    def test_delete_folder(self, drive):
        """Test deleting a folder moves it to trash."""
        folder = drive.create_folder(TEST_ROOT, "DeleteMe")
        assert folder is not None
        
        drive.delete_item(f"{TEST_ROOT}/DeleteMe")
        
        # Should no longer be found
        item = drive.get_item_by_path(f"{TEST_ROOT}/DeleteMe")
        assert item is None

    def test_delete_file(self, drive):
        """Test deleting a file moves it to trash."""
        drive.create_folder(TEST_ROOT, "DeleteFileTest")
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Delete me")
            temp_path = f.name
        
        try:
            drive.upload_file(temp_path, f"{TEST_ROOT}/DeleteFileTest/deleteme.txt")
            drive.delete_item(f"{TEST_ROOT}/DeleteFileTest/deleteme.txt")
            
            item = drive.get_item_by_path(f"{TEST_ROOT}/DeleteFileTest/deleteme.txt")
            assert item is None
        finally:
            os.unlink(temp_path)

    def test_delete_nonexistent_item(self, drive):
        """Test deleting non-existent item raises error."""
        with pytest.raises(GDriveError):
            drive.delete_item(f"{TEST_ROOT}/NonExistent12345")
