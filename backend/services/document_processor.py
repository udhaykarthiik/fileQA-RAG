import os
from PyPDF2 import PdfReader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from typing import List, Dict, Any

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
    
    def extract_text_from_pdf(self, file_path: str) -> str:
        """Extract text from PDF file"""
        text = ""
        try:
            reader = PdfReader(file_path)
            print(f"📖 PDF has {len(reader.pages)} pages")
            
            for page_num, page in enumerate(reader.pages):
                page_text = page.extract_text()
                text += page_text + "\n"
                print(f"   Page {page_num + 1}: {len(page_text)} characters")
            
            return text
        except Exception as e:
            raise Exception(f"Error processing PDF: {str(e)}")
    
    def extract_text_from_txt(self, file_path: str) -> str:
        """Extract text from TXT file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                text = file.read()
                print(f"📄 TXT file: {len(text)} characters")
                return text
        except Exception as e:
            raise Exception(f"Error processing TXT: {str(e)}")
    
    def process_file(self, file_path: str) -> str:
        """Process file based on extension"""
        file_extension = os.path.splitext(file_path)[1].lower()
        
        if file_extension == '.pdf':
            return self.extract_text_from_pdf(file_path)
        elif file_extension == '.txt':
            return self.extract_text_from_txt(file_path)
        else:
            raise Exception(f"Unsupported file type: {file_extension}")
    
    def create_chunks(self, text: str) -> List[Dict[str, Any]]:
        """Split text into chunks with metadata"""
        chunks = self.text_splitter.split_text(text)
        print(f"🔪 Split into {len(chunks)} chunks")
        
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
            print(f"   Chunk {i}: {len(chunk)} characters")
        
        return chunk_docs