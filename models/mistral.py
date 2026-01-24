"""Mistral AI LLM provider.

Uses Mistral AI API for document analysis and company name matching.
"""

import os
from typing import List, Optional, Tuple

from mistralai import Mistral

from .base import (
    LLM, LLMError, DocumentAnalysis,
    MAX_PATH_RETRIES,
    COMPARE_NAMES_PROMPT,
    DUPLICATE_DETECTION_PROMPT,
    FOLDER_MATCH_PROMPT,
)


class MistralLLM(LLM):
    """Mistral AI implementation for document analysis.
    
    Uses:
    - mistral-small-latest for text tasks (name comparison, deduplication)
    - File upload API for document analysis (OCR)
    """
    
    def __init__(self) -> None:
        """Initialize Mistral client.
        
        Raises:
            KeyError: If MISTRAL_API_KEY environment variable is not set
        """
        api_key = os.environ["MISTRAL_API_KEY"]
        self.client = Mistral(api_key=api_key)
    
    @property
    def name(self) -> str:
        return "mistral"
    
    def analyze_document(
        self,
        pdf_path: str,
        layout: str,
        hint: str = "",
        inbox_path: str = "",
        path_validator: Optional[callable] = None
    ) -> Optional[DocumentAnalysis]:
        """Analyze a PDF document using Mistral's file upload API.
        
        Uploads the PDF to Mistral for OCR processing, then asks the model
        to extract metadata and suggest a filing path.
        """
        # Check file size
        try:
            self._check_file_size(pdf_path)
        except ValueError as e:
            print(f"File too large: {e}. Routing to Other.")
            return self._create_fallback_analysis(pdf_path)
        
        # Upload the document to get a signed URL
        try:
            with open(pdf_path, 'rb') as file:
                upload_response = self.client.files.upload(
                    file={
                        "file_name": "uploaded_file.pdf",
                        "content": file,
                    },
                    purpose="ocr"
                )
            
            self.client.files.retrieve(file_id=upload_response.id)
            signed_url = self.client.files.get_signed_url(file_id=upload_response.id)
        except Exception as e:
            raise LLMError(f"Failed to upload document to Mistral: {e}")
        
        # Build the prompt
        prompt = self._build_analysis_prompt(layout, hint, inbox_path)
        
        # Build messages with document URL
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "document_url", "document_url": signed_url.url}
                ]
            }
        ]
        
        # Try to get a valid response with retries
        for attempt in range(MAX_PATH_RETRIES):
            try:
                response = self.client.chat.complete(
                    model="mistral-small-latest",
                    messages=messages
                )
                response_text = response.choices[0].message.content
            except Exception as e:
                raise LLMError(f"Mistral API error: {e}")
            
            # Parse the response
            result_dict = self._parse_analysis_response(response_text)
            
            if result_dict is None:
                print("LLM returned invalid response, routing to Other.")
                return self._create_fallback_analysis(pdf_path)
            
            # Check if path is valid (if validator provided)
            if path_validator is None or path_validator(result_dict['SUGGESTED_PATH']):
                return self._dict_to_analysis(result_dict)
            
            # Path invalid - add correction and retry
            print(f"Invalid path '{result_dict['SUGGESTED_PATH']}', "
                  f"asking LLM to retry ({attempt + 1}/{MAX_PATH_RETRIES})...")
            
            messages.append({"role": "assistant", "content": response_text})
            
            # Build specific feedback based on the invalid path
            feedback = "This is incorrect, the path that you suggested is not valid. "
            suggested = result_dict['SUGGESTED_PATH']
            if suggested.lower().endswith('by company'):
                feedback += "You used 'By company' literally - you must replace it with the actual company/entity name (e.g., 'Medical & Health/Bills/Chase' not 'Medical & Health/Bills/By company')."
            elif suggested.lower().endswith('by year'):
                feedback += "You used 'By year' literally - you must replace it with the actual year (e.g., 'Taxes/Federal/2024' not 'Taxes/Federal/By year')."
            else:
                feedback += "The path structure must match the layout. Where the layout shows 'By company', use the actual company/entity name. Where it shows 'By year', use the actual year. You may create new company or year folders as needed."
            feedback += " Try again."
            
            messages.append({
                "role": "user",
                "content": feedback
            })
        
        print(f"Failed to get valid path after {MAX_PATH_RETRIES} attempts, routing to Other.")
        return self._create_fallback_analysis(pdf_path)
    
    def compare_names(self, name1: str, name2: str) -> bool:
        """Check if two company names refer to the same entity."""
        prompt = COMPARE_NAMES_PROMPT.format(name1=name1, name2=name2)
        
        try:
            response = self.client.chat.complete(
                model="mistral-small-latest",
                messages=[{"role": "user", "content": prompt}]
            )
            result = response.choices[0].message.content.strip().upper()
            return result == "MATCH"
        except Exception as e:
            print(f"Warning: Name comparison failed: {e}")
            return False
    
    def find_duplicate_pair(
        self,
        names: List[str]
    ) -> Optional[Tuple[str, str]]:
        """Find a pair of duplicate folder names."""
        if len(names) < 2:
            return None
        
        # Build prompt with folder list
        prompt = DUPLICATE_DETECTION_PROMPT + "\n".join(f"- {name}" for name in names)
        
        try:
            response = self.client.chat.complete(
                model="mistral-small-latest",
                messages=[{"role": "user", "content": prompt}]
            )
            response_text = response.choices[0].message.content
            return self._parse_duplicate_response(response_text, names)
        except Exception as e:
            print(f"Warning: Duplicate detection failed: {e}")
            return None
    
    def find_matching_folder(
        self,
        new_name: str,
        existing_folders: List[str]
    ) -> Optional[str]:
        """Find if a new folder name matches any existing folder."""
        if not existing_folders:
            return None
        
        # Build the existing folders list for the prompt
        existing_list = "\n".join(f"- {folder}" for folder in existing_folders)
        prompt = FOLDER_MATCH_PROMPT.format(
            new_name=new_name,
            existing_list=existing_list
        )
        
        try:
            response = self.client.chat.complete(
                model="mistral-small-latest",
                messages=[{"role": "user", "content": prompt}]
            )
            response_text = response.choices[0].message.content
            return self._parse_folder_match_response(response_text, existing_folders)
        except Exception as e:
            print(f"Warning: Folder matching failed: {e}")
            return None
    
    def _create_fallback_analysis(self, pdf_path: str) -> DocumentAnalysis:
        """Create a fallback analysis for documents that can't be classified.
        
        Routes the document to 'Unsortable & Other' with minimal metadata.
        """
        # Extract title from filename
        base_name = os.path.splitext(os.path.basename(pdf_path))[0]
        title = base_name.replace('_', ' ').replace('-', ' ')
        
        return DocumentAnalysis(
            title=title,
            suggested_path="Unsortable & Other",
            confidence=0,
            year=None,
            date=None,
            entity=None,
            summary="Document could not be automatically classified."
        )
