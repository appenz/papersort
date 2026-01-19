import os
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from .docsorter import DocSorter

MAX_FILE_SIZE_MB = 50
MAX_PATH_RETRIES = 3


class LLMBase(ABC):
    """Abstract base class for LLM providers."""
    
    @abstractmethod
    def build_messages(self, doc: "DocSorter") -> List[Dict]:
        """Build the initial messages for the LLM request.
        
        Args:
            doc: The DocSorter instance containing the document to analyze.
            
        Returns:
            List of message dictionaries for the LLM API.
        """
        pass
    
    @abstractmethod
    def complete(self, messages: List[Dict]) -> Tuple[str, List[Dict]]:
        """Send messages to LLM and return response with updated messages.
        
        Args:
            messages: The conversation messages to send.
            
        Returns:
            Tuple of (response_text, updated_messages) where updated_messages
            includes the assistant's response appended.
        """
        pass
    
    def check_file_size(self, path: str) -> None:
        """Validate file size is under the limit.
        
        Args:
            path: Path to the file to check.
            
        Raises:
            ValueError: If the file exceeds the size limit.
        """
        file_size = os.path.getsize(path)
        if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
            raise ValueError(
                f"PDF exceeds {MAX_FILE_SIZE_MB}MB limit "
                f"({file_size / 1024 / 1024:.1f}MB)"
            )
    
    def sort(self, doc: "DocSorter") -> None:
        """Analyzes document and populates metadata fields.
        
        Args:
            doc: The DocSorter instance to populate with metadata.
        """
        from .docsorter import DocSorter
        
        self.check_file_size(doc.previous_path)
        
        messages = self.build_messages(doc)
        
        for attempt in range(MAX_PATH_RETRIES):
            result, messages = self.complete(messages)
            result_dict = result_to_dict(result)
            
            if result_dict is None:
                print("Error: LLM did not return a valid result.")
                return
            
            # Check if the suggested path is valid
            if DocSorter.path_exists(result_dict['SUGGESTED_PATH']):
                doc.title = result_dict['TITLE']
                doc.suggested_path = result_dict['SUGGESTED_PATH']
                doc.confidence = result_dict['CONFIDENCE']
                doc.year = result_dict['YEAR']
                doc.date = result_dict['DATE']
                doc.entity = result_dict['ENTITY']
                doc.summary = result_dict['SUMMARY']
                return
            
            # Path invalid - append correction message and retry
            print(f"Invalid path '{result_dict['SUGGESTED_PATH']}', asking LLM to retry ({attempt + 1}/{MAX_PATH_RETRIES})...")
            messages.append({
                "role": "user",
                "content": "This is incorrect, the path that you suggested is not valid. Try again."
            })
        
        print(f"Failed to get valid path after {MAX_PATH_RETRIES} attempts.")


def result_to_dict(result: str) -> Optional[Dict[str, str]]:
    """Converts the LLM response into a dictionary of metadata fields.
    
    Expected format:
    TITLE: <title>
    SUGGESTED_PATH: <path>
    CONFIDENCE: <confidence>
    YEAR: <year>
    DATE: <date>
    ENTITY: <entity>
    SUMMARY: <summary>
    
    Args:
        result: The raw text response from the LLM.
        
    Returns:
        A dictionary of metadata fields, or None if parsing failed.
    """
    result_dict = {}
    
    # Split the text into lines and process each line
    for line in result.split('\n'):
        line = line.strip()
        
        # Skip empty lines and separator lines
        if not line or line.startswith('---'):
            continue
            
        # Split on first colon
        parts = line.split(':', 1)
        if len(parts) != 2:
            continue
            
        key = parts[0].strip()
        value = parts[1].strip()
        
        # Store in dictionary if it's one of our expected fields
        if key in ['TITLE', 'SUGGESTED_PATH', 'CONFIDENCE', 'YEAR', 'DATE', 'ENTITY', 'SUMMARY']:
            result_dict[key] = value
    
    if len(result_dict) != 7:
        # Print which fields are missing
        missing_fields = set(['TITLE', 'SUGGESTED_PATH', 'CONFIDENCE', 'YEAR', 'DATE', 'ENTITY', 'SUMMARY']) - set(result_dict.keys())
        print(f"Incorrect format. Missing fields: {missing_fields}")
        return None

    return result_dict
