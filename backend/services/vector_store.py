import faiss
import numpy as np
import pickle
import os
from typing import List, Dict, Any

class VectorStore:
    """FAISS vector store for document embeddings"""
    
    def __init__(self, dimension: int):
        self.dimension = dimension
        self.index = faiss.IndexFlatL2(dimension)  # L2 distance index
        self.chunks = []  # Store original chunks with metadata
        self.embeddings = []  # Store embeddings
    
    def add_chunks(self, chunks: List[Dict[str, Any]]):
        """Add chunks with embeddings to the store"""
        for chunk in chunks:
            if 'embedding' not in chunk:
                raise ValueError("Chunk missing embedding")
            
            embedding = np.array(chunk['embedding']).astype('float32').reshape(1, -1)
            self.index.add(embedding)
            self.chunks.append(chunk)
            self.embeddings.append(chunk['embedding'])
    
    def similarity_search(self, query_embedding: List[float], k: int = 4) -> List[Dict[str, Any]]:
        """Search for most similar chunks"""
        query_vector = np.array(query_embedding).astype('float32').reshape(1, -1)
        
        # Search
        distances, indices = self.index.search(query_vector, min(k, len(self.chunks)))
        
        # Return relevant chunks
        results = []
        for i, idx in enumerate(indices[0]):
            if idx != -1:  # Valid index
                chunk = self.chunks[idx].copy()
                chunk['similarity_score'] = float(1 / (1 + distances[0][i]))  # Convert distance to similarity
                results.append(chunk)
        
        return results
    
    def save(self, file_path: str):
        """Save the vector store to disk"""
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        # Save FAISS index
        faiss.write_index(self.index, f"{file_path}.index")
        
        # Save chunks and metadata
        with open(f"{file_path}.pkl", 'wb') as f:
            pickle.dump({
                'chunks': self.chunks,
                'dimension': self.dimension
            }, f)
    
    def load(self, file_path: str):
        """Load the vector store from disk"""
        # Load FAISS index
        self.index = faiss.read_index(f"{file_path}.index")
        
        # Load chunks and metadata
        with open(f"{file_path}.pkl", 'rb') as f:
            data = pickle.load(f)
            self.chunks = data['chunks']
            self.dimension = data['dimension']
        
        return self