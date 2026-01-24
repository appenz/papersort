"""OpenAI LLM provider.

Uses OpenAI API for document analysis and company name matching.
"""

import base64
import os
from typing import List, Optional, Tuple

from openai import OpenAI

from .base import (
    LLM, LLMError, DocumentAnalysis,
    MAX_PATH_RETRIES,
    COMPARE_NAMES_PROMPT,
    DUPLICATE_DETECTION_PROMPT,
    FOLDER_MATCH_PROMPT,
)


class OpenAILLM(LLM):
    """OpenAI implementation for document analysis.
    
    Uses:
    - gpt-5.1 for all tasks (document analysis with vision, name comparison)
    - Base64 encoding for PDF documents
    """
    
    def __init__(self) -> None:
        """Initialize OpenAI client.
        
        Uses OPENAI_API_KEY environment variable automatically.
        """
        self.client = OpenAI()
    
    @property
    def name(self) -> str:
        return "openai"
    
    def analyze_document(
        self,
        pdf_path: str,
        layout: str,
        hint: str = "",
        inbox_path: str = "",
        path_validator: Optional[callable] = None
    ) -> Optional[DocumentAnalysis]:
        """Analyze a PDF document using OpenAI's GPT-4 with vision.
        
        Encodes the PDF as base64 and sends it to GPT-4o for analysis.
        """
        # Check file size
        try:
            self._check_file_size(pdf_path)
        except ValueError as e:
            print(f"File too large: {e}. Routing to Other.")
            return self._create_fallback_analysis(pdf_path)
        
        # Read and base64-encode the PDF
        try:
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()
            base64_pdf = base64.b64encode(pdf_bytes).decode("utf-8")
        except Exception as e:
            raise LLMError(f"Failed to read PDF file: {e}")
        
        # Build the prompt
        prompt = self._build_analysis_prompt(layout, hint, inbox_path)
        
        # Build messages with base64-encoded PDF
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "file",
                        "file": {
                            "filename": os.path.basename(pdf_path),
                            "file_data": f"data:application/pdf;base64,{base64_pdf}"
                        }
                    }
                ]
            }
        ]
        
        # Try to get a valid response with retries
        for attempt in range(MAX_PATH_RETRIES):
            try:
                response = self.client.chat.completions.create(
                    model="gpt-4o",
                    messages=messages
                )
                response_text = response.choices[0].message.content
            except Exception as e:
                raise LLMError(f"OpenAI API error: {e}")
            
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
            response = self.client.chat.completions.create(
                model="gpt-5.1",
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
            response = self.client.chat.completions.create(
                model="gpt-4o",
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
            response = self.client.chat.completions.create(
                model="gpt-4o",
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
