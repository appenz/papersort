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
    
    def sort(self, doc: "DocSorter") -> bool:
        """Analyzes document and populates metadata fields.
        
        Args:
            doc: The DocSorter instance to populate with metadata.
            
        Returns:
            True if successful, False if failed to get valid path.
        """
        from .docsorter import DocSorter
        
        try:
            self.check_file_size(doc.previous_path)
        except ValueError as e:
            print(f"File too large: {e}. Routing to Other.")
            self._set_other_defaults(doc)
            return True
        
        messages = self.build_messages(doc)
        
        for attempt in range(MAX_PATH_RETRIES):
            result, messages = self.complete(messages)
            result_dict = result_to_dict(result)
            
            if result_dict is None:
                # LLM returned invalid response - route to Other
                print("LLM returned invalid response, routing to Other.")
                self._set_other_defaults(doc)
                return True
            
            # Check if the suggested path is valid
            if DocSorter.path_exists(result_dict['SUGGESTED_PATH']):
                doc.title = result_dict['TITLE']
                doc.suggested_path = result_dict['SUGGESTED_PATH']
                doc.confidence = result_dict['CONFIDENCE']
                doc.year = result_dict['YEAR']
                doc.date = result_dict['DATE']
                doc.entity = result_dict['ENTITY']
                doc.summary = result_dict['SUMMARY']
                return True
            
            # Path invalid - append correction message and retry
            print(f"Invalid path '{result_dict['SUGGESTED_PATH']}', asking LLM to retry ({attempt + 1}/{MAX_PATH_RETRIES})...")
            messages.append({
                "role": "user",
                "content": "This is incorrect, the path that you suggested is not valid. Try again."
            })
        
        print(f"Failed to get valid path after {MAX_PATH_RETRIES} attempts, routing to Other.")
        self._set_other_defaults(doc)
        return True
    
    def _set_other_defaults(self, doc: "DocSorter") -> None:
        """Set default values for documents that can't be properly classified.
        
        Routes the document to 'Other' with minimal metadata derived from filename.
        """
        import os
        
        # Extract a title from the filename (without extension)
        base_name = os.path.splitext(doc.file_name)[0]
        # Clean up common filename patterns (underscores, dashes)
        title = base_name.replace('_', ' ').replace('-', ' ')
        
        doc.title = title
        doc.suggested_path = "Unsortable & Other"
        doc.confidence = 0
        doc.year = None
        doc.date = None
        doc.entity = None
        doc.summary = "Document could not be automatically classified."


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


# Prompt for duplicate company detection
DUPLICATE_DETECTION_PROMPT = """You are analyzing a list of company folder names to find duplicates.
These folders are meant to store documents from different companies, but sometimes the same company
has been filed under different names (e.g., "Chase Bank" and "Chase", or "Goldman Sachs" and "GS").

Your task is to find EXACTLY ONE pair of folder names that likely refer to the same company.

Rules:
- Only identify folders that clearly refer to the SAME company (not related companies or subsidiaries)
- If you find multiple potential duplicates, return only the MOST OBVIOUS one
- If no duplicates exist, return "None"

You MUST respond in EXACTLY this format (no other text):
DUPLICATE: FolderA | FolderB

Or if no duplicates:
DUPLICATE: None

Here are the folder names to analyze:
"""


def find_duplicate_pair(folder_names: List[str], llm_provider: str = "mistral") -> Optional[Tuple[str, str]]:
    """Find a pair of folder names that likely refer to the same company.
    
    Uses an LLM to analyze folder names and detect potential duplicates.
    Returns at most ONE pair per call to allow for user confirmation before
    continuing the search.
    
    Args:
        folder_names: List of company folder names to analyze
        llm_provider: LLM provider to use ("mistral" or "openai")
        
    Returns:
        Tuple of (folder1, folder2) if a duplicate is found, None otherwise
    """
    if len(folder_names) < 2:
        return None
    
    # Build the prompt with the folder list
    prompt = DUPLICATE_DETECTION_PROMPT + "\n".join(f"- {name}" for name in folder_names)
    
    messages = [{"role": "user", "content": prompt}]
    
    # Get LLM response
    if llm_provider == "openai":
        from .llm_openai import OpenAILLM
        llm = OpenAILLM()
    else:
        from .llm_mistral import MistralLLM
        llm = MistralLLM()
    
    response, _ = llm.complete(messages)
    
    # Parse the response
    return _parse_duplicate_response(response, folder_names)


def _parse_duplicate_response(response: str, valid_folders: List[str]) -> Optional[Tuple[str, str]]:
    """Parse the LLM response for duplicate detection.
    
    Args:
        response: Raw LLM response text
        valid_folders: List of valid folder names to validate against
        
    Returns:
        Tuple of (folder1, folder2) if valid duplicate found, None otherwise
    """
    # Look for the DUPLICATE: line
    for line in response.strip().split('\n'):
        line = line.strip()
        if line.upper().startswith('DUPLICATE:'):
            value = line.split(':', 1)[1].strip()
            
            # Check for "None" response
            if value.lower() == 'none':
                return None
            
            # Parse "FolderA | FolderB" format
            if '|' in value:
                parts = [p.strip() for p in value.split('|')]
                if len(parts) == 2:
                    folder1, folder2 = parts
                    
                    # Validate both folders exist in the original list
                    if folder1 in valid_folders and folder2 in valid_folders:
                        return (folder1, folder2)
                    
                    # Try case-insensitive match
                    folder1_match = next((f for f in valid_folders if f.lower() == folder1.lower()), None)
                    folder2_match = next((f for f in valid_folders if f.lower() == folder2.lower()), None)
                    
                    if folder1_match and folder2_match:
                        return (folder1_match, folder2_match)
                    
                    print(f"Warning: LLM returned folders not in list: {folder1}, {folder2}")
    
    return None
