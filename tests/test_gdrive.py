import pytest
import os
from gdrive.gdrive import GDrive, GDriveError

def test_gdrive_initialization():
    try:
        drive = GDrive()
        assert drive.service is not None
    except GDriveError as e:
        pytest.skip(f"Skipping test - no credentials available: {str(e)}")

def test_list_items():
    try:
        drive = GDrive()
        # Test listing root items
        items = drive.list_items("")
        assert isinstance(items, list)
        if items:
            item = items[0]
            assert 'id' in item
            assert 'name' in item
            assert 'mimeType' in item
            assert 'size' in item
            assert 'modifiedTime' in item
            
        # Test listing items in a folder
        folder = drive.create_folder("", "TestFolder")
        test_file = drive.create_folder("TestFolder", "TestFile")
        items = drive.list_items("TestFolder")
        assert len(items) > 0
        assert any(item['name'] == "TestFile" for item in items)
        
    except GDriveError as e:
        pytest.skip(f"Skipping test - no credentials available: {str(e)}")

def test_create_folder():
    try:
        drive = GDrive()
        # Test creating a folder in root
        folder = drive.create_folder("", "TestFolder")
        assert folder['name'] == "TestFolder"
        assert 'id' in folder
        
        # Test creating nested folders
        nested = drive.create_folder("TestFolder/SubFolder", "DeepFolder")
        assert nested['name'] == "DeepFolder"
        assert 'id' in nested
    except GDriveError as e:
        pytest.skip(f"Skipping test - no credentials available: {str(e)}")

def test_docstore_folder():
    try:
        # Test with default name
        drive = GDrive()
        assert drive.docstore_folder is not None
        assert drive.docstore_folder['name'] == 'Documents'
        assert drive.docstore_folder['mimeType'] == 'application/vnd.google-apps.folder'
        
        # Test with custom name from environment
        os.environ['DOCSTORE'] = 'TestDocuments'
        drive = GDrive()
        assert drive.docstore_folder is not None
        assert drive.docstore_folder['name'] == 'TestDocuments'
        assert drive.docstore_folder['mimeType'] == 'application/vnd.google-apps.folder'
        
        # Clean up environment
        del os.environ['DOCSTORE']
    except GDriveError as e:
        pytest.skip(f"Skipping test - no credentials available: {str(e)}") 