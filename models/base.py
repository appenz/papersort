"""Base classes for LLM providers.

This module defines the abstract interface that all LLM backends must implement.
"""

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


class LLMError(Exception):
    """Base exception for LLM operations."""
    pass


@dataclass
class DocumentAnalysis:
    """Result of analyzing a document.
    
    Attributes:
        title: Short title for the document (max 10 words)
        suggested_path: Where the document should be filed in the layout
        confidence: Confidence in the suggested path (1-10)
        year: The year the document is about (may differ from date)
        date: Document date in YYYY-MM format
        entity: Company/organization the document is from/about
        summary: Brief description (max 100 words)
    """
    title: str
    suggested_path: str
    confidence: int
    year: Optional[str]
    date: Optional[str]
    entity: Optional[str]
    summary: str


# Maximum file size for document analysis (50MB)
MAX_FILE_SIZE_MB = 50

# Maximum retries for getting a valid path from LLM
MAX_PATH_RETRIES = 3


# Document analysis prompt template
DOCUMENT_ANALYSIS_PROMPT = """You are a helpful assistant analyzing a document. Your output should have exactly the following format:

---
TITLE: <a short title>
SUGGESTED_PATH: <where the document should be filed>
CONFIDENCE: <confidence in the suggested path on a scale of 1 (lowest) to 10 (highest)>
YEAR: <the year the document is about>
DATE: <the date the document was created or sent>
ENTITY: <the entity the document is about>
SUMMARY: <a short summary of the document, not more than 100 words>
---

Some specific guidelines:
- Title is a short title of the document, not more than 10 words.
- The year is the year the document is about, which may be different from the year in the date. For a tax document, it is the tax year.
- Entity is often the name of the company or organization the document is from or to. For a bank statement, it is the bank's name.
- Summary is a short summary of the document, not more than 100 words.
- Suggested path is the most important part of the output. It is where the document should be filed.

MOST IMPORTANT: Make sure the suggested path is a valid path in the layout below! Do not invent paths that are not in the layout.

The layout description for the document store follow after this line.
---
"""


# Company name comparison prompt
COMPARE_NAMES_PROMPT = """You are a helpful assistant that identifies if two company or organization names refer to the same entity.

Compare these two names:
1. "{name1}"
2. "{name2}"

Consider that:
- Different capitalizations (e.g., "Chase" vs "CHASE") are the same
- Abbreviations vs full names (e.g., "JP Morgan" vs "JPMorgan Chase") are the same
- Minor punctuation differences (e.g., "J.P. Morgan" vs "JP Morgan") are the same
- Parent/subsidiary relationships where the name is essentially the same are matches

Respond with EXACTLY one word: MATCH or NO_MATCH
"""


# Duplicate detection prompt for folder names
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


# Prompt for matching a new folder name against existing folders
FOLDER_MATCH_PROMPT = """You are checking if a new company folder name should use an existing folder instead.

New folder name: "{new_name}"

Existing folders in this directory:
{existing_list}

Determine if the new name is a SPELLING VARIATION of any existing folder (same company, different formatting).

MATCH examples (same company, different spelling/format):
- "JPMorgan" matches "J.P. Morgan" or "JP Morgan Chase"
- "ATT" matches "AT&T"
- "GS" matches "Goldman Sachs"
- "Citi" matches "Citibank" or "Citigroup"
- "Dr Jones" matches "Dr. Jones" or "Jones M.D." or "Bob Jones, Doctor of Pediatrics" (you can assume last names are unique and can be used to identify the company)

NO MATCH examples (different companies or intentionally separate):
- "Chase Bank" does NOT match "Wells Fargo" (different companies)
- "Bank of America" does NOT match "American Bank" (different companies despite similar words)
- If BOTH "Chase" AND "JPMorgan" exist as separate folders, a new "JPMorgan Chase" should NOT match either (the user has chosen to keep them separate)

Respond with EXACTLY one line:
MATCH: <exact existing folder name from the list>
or
NO_MATCH
"""


class LLM(ABC):
    """Abstract base class for LLM providers.
    
    All LLM providers (Mistral, OpenAI) implement this interface for
    document analysis and company name matching.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name (e.g., 'mistral', 'openai')."""
        pass
    
    @abstractmethod
    def analyze_document(
        self,
        pdf_path: str,
        layout: str,
        hint: str = "",
        inbox_path: str = "",
        path_validator: Optional[callable] = None
    ) -> Optional[DocumentAnalysis]:
        """Analyze a PDF document and return structured metadata.
        
        Args:
            pdf_path: Path to the PDF file to analyze
            layout: The layout.txt content describing the folder structure
            hint: Optional hint about the document (e.g., previous filing path)
            inbox_path: Optional inbox path where the document came from
            path_validator: Optional function to validate suggested paths.
                           If provided, will retry if path is invalid.
        
        Returns:
            DocumentAnalysis with extracted metadata, or None if analysis failed
            
        Raises:
            LLMError: If analysis fails after all retries
            ValueError: If file is too large
        """
        pass
    
    @abstractmethod
    def compare_names(self, name1: str, name2: str) -> bool:
        """Check if two company/entity names refer to the same organization.
        
        Args:
            name1: First company name
            name2: Second company name
            
        Returns:
            True if names refer to the same company, False otherwise
        """
        pass
    
    @abstractmethod
    def find_duplicate_pair(
        self,
        names: List[str]
    ) -> Optional[Tuple[str, str]]:
        """Find a pair of duplicate names in a list.
        
        Analyzes a list of folder/company names and returns the first
        pair that likely refers to the same entity.
        
        Args:
            names: List of company/folder names to analyze
            
        Returns:
            Tuple of (name1, name2) if duplicates found, None otherwise
        """
        pass
    
    @abstractmethod
    def find_matching_folder(
        self,
        new_name: str,
        existing_folders: List[str]
    ) -> Optional[str]:
        """Find if a new folder name matches any existing folder.
        
        Checks if a proposed new folder name is a spelling variation of
        any existing folder (same company, different formatting).
        
        Args:
            new_name: The proposed new folder name
            existing_folders: List of existing folder names to check against
            
        Returns:
            The matching existing folder name if found, None otherwise
        """
        pass
    
    # =========================================================================
    # Helper methods (shared by all implementations)
    # =========================================================================
    
    def _check_file_size(self, path: str) -> None:
        """Validate file size is under the limit.
        
        Args:
            path: Path to the file to check
            
        Raises:
            ValueError: If the file exceeds the size limit
        """
        file_size = os.path.getsize(path)
        if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
            raise ValueError(
                f"PDF exceeds {MAX_FILE_SIZE_MB}MB limit "
                f"({file_size / 1024 / 1024:.1f}MB)"
            )
    
    def _build_analysis_prompt(self, layout: str, hint: str = "", inbox_path: str = "") -> str:
        """Build the full prompt for document analysis.
        
        Args:
            layout: The layout.txt content
            hint: Optional hint about the document
            inbox_path: Optional inbox path where the document came from
            
        Returns:
            Complete prompt string
        """
        prompt = DOCUMENT_ANALYSIS_PROMPT + layout
        if inbox_path:
            prompt += f"\n---\nThis document came from the inbox path: {inbox_path}"
        if hint:
            prompt += f"\n---\nOne last hint, in a different place this document was filed as: {hint}"
        return prompt
    
    def _parse_analysis_response(self, response: str) -> Optional[Dict[str, str]]:
        """Parse the LLM response into a dictionary of metadata fields.
        
        Expected format:
        TITLE: <title>
        SUGGESTED_PATH: <path>
        CONFIDENCE: <confidence>
        YEAR: <year>
        DATE: <date>
        ENTITY: <entity>
        SUMMARY: <summary>
        
        Args:
            response: The raw text response from the LLM
            
        Returns:
            Dictionary of metadata fields, or None if parsing failed
        """
        result_dict = {}
        expected_fields = ['TITLE', 'SUGGESTED_PATH', 'CONFIDENCE', 'YEAR', 'DATE', 'ENTITY', 'SUMMARY']
        
        for line in response.split('\n'):
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
            
            if key in expected_fields:
                result_dict[key] = value
        
        if len(result_dict) != 7:
            missing = set(expected_fields) - set(result_dict.keys())
            print(f"Incorrect format. Missing fields: {missing}")
            return None
        
        return result_dict
    
    def _dict_to_analysis(self, data: Dict[str, str]) -> DocumentAnalysis:
        """Convert parsed dictionary to DocumentAnalysis dataclass.
        
        Args:
            data: Dictionary with analysis fields
            
        Returns:
            DocumentAnalysis instance
        """
        return DocumentAnalysis(
            title=data['TITLE'],
            suggested_path=data['SUGGESTED_PATH'],
            confidence=int(data['CONFIDENCE']) if data['CONFIDENCE'].isdigit() else 5,
            year=data['YEAR'] if data['YEAR'] and data['YEAR'].lower() != 'none' else None,
            date=data['DATE'] if data['DATE'] and data['DATE'].lower() != 'none' else None,
            entity=data['ENTITY'] if data['ENTITY'] and data['ENTITY'].lower() != 'none' else None,
            summary=data['SUMMARY']
        )
    
    def _parse_duplicate_response(
        self,
        response: str,
        valid_names: List[str]
    ) -> Optional[Tuple[str, str]]:
        """Parse the LLM response for duplicate detection.
        
        Args:
            response: Raw LLM response text
            valid_names: List of valid names to validate against
            
        Returns:
            Tuple of (name1, name2) if valid duplicate found, None otherwise
        """
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
                        name1, name2 = parts
                        
                        # Validate both names exist in the original list
                        if name1 in valid_names and name2 in valid_names:
                            return (name1, name2)
                        
                        # Try case-insensitive match
                        name1_match = next((n for n in valid_names if n.lower() == name1.lower()), None)
                        name2_match = next((n for n in valid_names if n.lower() == name2.lower()), None)
                        
                        if name1_match and name2_match:
                            return (name1_match, name2_match)
                        
                        print(f"Warning: LLM returned names not in list: {name1}, {name2}")
        
        return None
    
    def _parse_folder_match_response(
        self,
        response: str,
        valid_folders: List[str]
    ) -> Optional[str]:
        """Parse the LLM response for folder matching.
        
        Args:
            response: Raw LLM response text
            valid_folders: List of valid folder names to validate against
            
        Returns:
            The matching folder name if found and valid, None otherwise
        """
        for line in response.strip().split('\n'):
            line = line.strip()
            
            if line.upper().startswith('NO_MATCH') or line.upper() == 'NO MATCH':
                return None
            
            if line.upper().startswith('MATCH:'):
                folder_name = line.split(':', 1)[1].strip()
                
                # Validate the folder exists in the list (exact match)
                if folder_name in valid_folders:
                    return folder_name
                
                # Try case-insensitive match
                folder_match = next(
                    (f for f in valid_folders if f.lower() == folder_name.lower()),
                    None
                )
                if folder_match:
                    return folder_match
                
                print(f"Warning: LLM returned folder not in list: {folder_name}")
                return None
        
        return None
