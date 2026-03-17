import os
import tempfile
from typing import List, Dict, Any
from PyPDF2 import PdfReader
from langchain.text_splitter import RecursiveCharacterTextSplitter

class DocumentProcessor:
    """Handles document processing: text extraction and chunking"""
    
    def __init__(self, chunk_size=1000, chunk_overlap=200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
            separators=["\n\n", "\n", " ", ""]
        )
    
    def process_pdf(self, file_path: str) -> str:
        """Extract text from PDF file"""
        text = ""
        try:
            reader = PdfReader(file_path)
            for page in reader.pages:
                text += page.extract_text() + "\n"
            return text
        except Exception as e:
            raise Exception(f"Error processing PDF: {str(e)}")
    
    def process_txt(self, file_path: str) -> str:
        """Extract text from TXT file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                return file.read()
        except Exception as e:
            raise Exception(f"Error processing TXT: {str(e)}")
    
    def process_file(self, file_path: str, file_extension: str) -> str:
        """Process file based on extension"""
        if file_extension.lower() == '.pdf':
            return self.process_pdf(file_path)
        elif file_extension.lower() == '.txt':
            return self.process_txt(file_path)
        else:
            raise Exception(f"Unsupported file type: {file_extension}")
    
    def create_chunks(self, text: str) -> List[Dict[str, Any]]:
        """Split text into chunks with metadata"""
        chunks = self.text_splitter.split_text(text)
        
        chunk_docs = []
        for i, chunk in enumerate(chunks):
            chunk_docs.append({
                "id": f"chunk_{i}",
                "text": chunk,
                "metadata": {
                    "chunk_index": i,
                    "chunk_size": len(chunk)
                }
            })
        
        return chunk_docs
    
    def save_uploaded_file(self, uploaded_file, upload_folder: str) -> str:
        """Save uploaded file to disk and return path"""
        os.makedirs(upload_folder, exist_ok=True)
        
        filename = uploaded_file.filename
        file_path = os.path.join(upload_folder, filename)
        
        # Save the file
        uploaded_file.save(file_path)
        
        return file_path