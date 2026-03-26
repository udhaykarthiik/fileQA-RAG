import os
from typing import List, Dict, Any

try:
    from PyPDF2 import PdfReader
except ImportError:
    from pypdf import PdfReader


class DocumentProcessor:
    """Handles document processing: text extraction and chunking — no langchain dependency"""

    def __init__(self, chunk_size=1000, chunk_overlap=200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def extract_text_from_pdf(self, file_path: str) -> str:
        """Extract text from PDF file"""
        text = ""
        try:
            reader = PdfReader(file_path)
            print(f"📖 PDF has {len(reader.pages)} pages")
            for page_num, page in enumerate(reader.pages):
                page_text = page.extract_text() or ""
                text += page_text + "\n"
                print(f"   Page {page_num + 1}: {len(page_text)} characters")
            return text
        except Exception as e:
            raise Exception(f"Error processing PDF: {str(e)}")

    def extract_text_from_txt(self, file_path: str) -> str:
        """Extract text from TXT file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()
            print(f"📄 TXT file: {len(text)} characters")
            return text
        except Exception as e:
            raise Exception(f"Error processing TXT: {str(e)}")

    def process_file(self, file_path: str) -> str:
        """Process file based on extension"""
        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.pdf':
            return self.extract_text_from_pdf(file_path)
        elif ext == '.txt':
            return self.extract_text_from_txt(file_path)
        else:
            raise Exception(f"Unsupported file type: {ext}")

    def create_chunks(self, text: str) -> List[Dict[str, Any]]:
        """
        Split text into overlapping chunks.
        Replicates LangChain's RecursiveCharacterTextSplitter logic
        using ['\n\n', '\n', ' ', ''] separators — no external dependency.
        """
        chunks = self._recursive_split(text, ["\n\n", "\n", " ", ""])
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

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _recursive_split(self, text: str, separators: List[str]) -> List[str]:
        """Recursively split text using the first separator that works."""
        final_chunks: List[str] = []

        # Pick the first separator that actually appears in the text
        separator = separators[-1]
        for sep in separators:
            if sep == "":
                separator = sep
                break
            if sep in text:
                separator = sep
                break

        splits = text.split(separator) if separator else list(text)

        good: List[str] = []  # splits short enough to merge
        for s in splits:
            if len(s) < self.chunk_size:
                good.append(s)
            else:
                # Flush what we have first
                if good:
                    final_chunks.extend(self._merge_splits(good, separator))
                    good = []
                # Recurse on the oversized piece with the next separator
                remaining = separators[separators.index(separator) + 1:] if separator in separators else [""]
                final_chunks.extend(self._recursive_split(s, remaining or [""]))

        if good:
            final_chunks.extend(self._merge_splits(good, separator))

        return final_chunks

    def _merge_splits(self, splits: List[str], separator: str) -> List[str]:
        """Merge small splits into chunks of ~chunk_size with overlap."""
        chunks: List[str] = []
        current_parts: List[str] = []
        current_len = 0
        sep_len = len(separator)

        for part in splits:
            part_len = len(part)
            # +sep_len for the separator we'll join with
            if current_len + part_len + (sep_len if current_parts else 0) > self.chunk_size and current_parts:
                chunk = separator.join(current_parts).strip()
                if chunk:
                    chunks.append(chunk)
                # Keep overlap: drop parts from the front until we're under chunk_overlap
                while current_parts and current_len > self.chunk_overlap:
                    removed = current_parts.pop(0)
                    current_len -= len(removed) + sep_len

            current_parts.append(part)
            current_len += part_len + (sep_len if len(current_parts) > 1 else 0)

        # Final chunk
        if current_parts:
            chunk = separator.join(current_parts).strip()
            if chunk:
                chunks.append(chunk)

        return chunks