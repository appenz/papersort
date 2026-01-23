"""Tests for LocalDriver.

These tests run against /tmp so no external dependencies needed.
"""

import os
import tempfile
import shutil
import pytest

from storage import LocalDriver, StorageError


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    dir_path = tempfile.mkdtemp(prefix="papersort_test_")
    yield dir_path
    # Cleanup
    shutil.rmtree(dir_path, ignore_errors=True)


@pytest.fixture
def driver(temp_dir):
    """Create a LocalDriver instance."""
    return LocalDriver(temp_dir)


@pytest.fixture
def populated_dir(temp_dir):
    """Create a temp directory with some test files and folders."""
    # Create files
    with open(os.path.join(temp_dir, "file1.txt"), "w") as f:
        f.write("content1")
    with open(os.path.join(temp_dir, "file2.pdf"), "w") as f:
        f.write("pdf content")
    
    # Create subfolder with files
    subdir = os.path.join(temp_dir, "subdir")
    os.makedirs(subdir)
    with open(os.path.join(subdir, "nested.txt"), "w") as f:
        f.write("nested content")
    with open(os.path.join(subdir, "nested.pdf"), "w") as f:
        f.write("nested pdf")
    
    return temp_dir


class TestLocalDriverBasics:
    """Basic functionality tests."""
    
    def test_display_name(self, driver, temp_dir):
        assert temp_dir in driver.display_name
        assert "local" in driver.display_name
    
    def test_nonexistent_root_raises(self):
        with pytest.raises(StorageError):
            LocalDriver("/nonexistent/path/12345")


class TestListFiles:
    """Tests for list_files()."""
    
    def test_list_files_empty(self, driver):
        files = driver.list_files()
        assert files == []
    
    def test_list_files_flat(self, populated_dir):
        driver = LocalDriver(populated_dir)
        files = driver.list_files()
        names = [f.name for f in files]
        assert "file1.txt" in names
        assert "file2.pdf" in names
        assert len(files) == 2  # Doesn't include nested
    
    def test_list_files_recursive(self, populated_dir):
        driver = LocalDriver(populated_dir)
        files = driver.list_files(recursive=True)
        names = [f.name for f in files]
        assert "file1.txt" in names
        assert "nested.txt" in names
        assert len(files) == 4
    
    def test_list_files_extension_filter(self, populated_dir):
        driver = LocalDriver(populated_dir)
        files = driver.list_files(recursive=True, extension=".pdf")
        names = [f.name for f in files]
        assert "file2.pdf" in names
        assert "nested.pdf" in names
        assert len(files) == 2


class TestListFolders:
    """Tests for list_folders()."""
    
    def test_list_folders(self, populated_dir):
        driver = LocalDriver(populated_dir)
        folders = driver.list_folders()
        names = [f.name for f in folders]
        assert "subdir" in names
        assert len(folders) == 1


class TestFileExists:
    """Tests for file_exists()."""
    
    def test_file_exists_true(self, populated_dir):
        driver = LocalDriver(populated_dir)
        assert driver.file_exists("file1.txt") is True
    
    def test_file_exists_false(self, populated_dir):
        driver = LocalDriver(populated_dir)
        assert driver.file_exists("nonexistent.txt") is False
    
    def test_file_exists_folder_returns_false(self, populated_dir):
        driver = LocalDriver(populated_dir)
        assert driver.file_exists("subdir") is False


class TestReadText:
    """Tests for read_text()."""
    
    def test_read_text(self, populated_dir):
        driver = LocalDriver(populated_dir)
        content = driver.read_text("file1.txt")
        assert content == "content1"
    
    def test_read_text_nonexistent_raises(self, driver):
        with pytest.raises(StorageError):
            driver.read_text("nonexistent.txt")


class TestDownloadToTemp:
    """Tests for download_to_temp()."""
    
    def test_download_to_temp_returns_original_path(self, populated_dir):
        driver = LocalDriver(populated_dir)
        path = driver.download_to_temp("file1.txt")
        # For local driver, returns original path
        assert path == os.path.join(populated_dir, "file1.txt")


class TestUpload:
    """Tests for upload()."""
    
    def test_upload(self, driver, temp_dir):
        # Create a source file
        src_path = os.path.join(temp_dir, "source.txt")
        with open(src_path, "w") as f:
            f.write("upload content")
        
        driver.upload(src_path, "uploaded.txt")
        
        assert driver.file_exists("uploaded.txt")
        assert driver.read_text("uploaded.txt") == "upload content"
    
    def test_upload_creates_folders(self, driver, temp_dir):
        src_path = os.path.join(temp_dir, "source.txt")
        with open(src_path, "w") as f:
            f.write("content")
        
        driver.upload(src_path, "new/nested/folder/file.txt")
        
        assert driver.file_exists("new/nested/folder/file.txt")


class TestMove:
    """Tests for move()."""
    
    def test_move(self, populated_dir):
        driver = LocalDriver(populated_dir)
        
        # Create destination folder
        os.makedirs(os.path.join(populated_dir, "dest"))
        
        driver.move("file1.txt", "dest")
        
        assert not driver.file_exists("file1.txt")
        assert driver.file_exists("dest/file1.txt")


class TestDelete:
    """Tests for delete()."""
    
    def test_delete_file(self, populated_dir):
        driver = LocalDriver(populated_dir)
        
        assert driver.file_exists("file1.txt")
        driver.delete("file1.txt")
        assert not driver.file_exists("file1.txt")
    
    def test_delete_folder(self, populated_dir):
        driver = LocalDriver(populated_dir)
        
        folders = [f.name for f in driver.list_folders()]
        assert "subdir" in folders
        
        driver.delete("subdir")
        
        folders = [f.name for f in driver.list_folders()]
        assert "subdir" not in folders


class TestSanitizeFilename:
    """Tests for sanitize_filename()."""
    
    def test_removes_forbidden_chars(self, driver):
        assert driver.sanitize_filename("file/name") == "file-name"
        assert driver.sanitize_filename("file:name") == "file-name"
        assert driver.sanitize_filename("file*name") == "filename"
        assert driver.sanitize_filename('file"name') == "file'name"
    
    def test_trims_whitespace(self, driver):
        assert driver.sanitize_filename("  file  ") == "file"
    
    def test_limits_length(self, driver):
        long_name = "a" * 150
        result = driver.sanitize_filename(long_name)
        assert len(result) <= 100
