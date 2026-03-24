# from flask import Blueprint, request, jsonify, current_app
# from services.embedding_service import EmbeddingService
# from services.vector_store import VectorStore
# from services.groq_service import GroqService
# import os

# chat_bp = Blueprint('chat', __name__)

# # Initialize services
# embedding_service = EmbeddingService()
# groq_service = GroqService()

# @chat_bp.route('/chat', methods=['POST'])
# def chat():
#     data = request.json
    
#     if not data or 'message' not in data:
#         return jsonify({'error': 'No message provided'}), 400
    
#     message = data['message']
#     file_id = data.get('file_id')
#     history = data.get('history', [])
    
#     if not file_id:
#         return jsonify({'error': 'No file selected'}), 400
    
#     try:
#         # Load vector store for this file
#         vector_store_path = os.path.join('vector_store', file_id)
        
#         if not os.path.exists(f"{vector_store_path}.index"):
#             return jsonify({'error': 'File not found or not processed'}), 404
        
#         # Load vector store
#         vector_store = VectorStore(dimension=embedding_service.embedding_dim)
#         vector_store.load(vector_store_path)
        
#         # Generate embedding for question
#         question_embedding = embedding_service.generate_embedding(message)
        
#         # Search for relevant chunks
#         relevant_chunks = vector_store.similarity_search(question_embedding, k=4)
        
#         if not relevant_chunks:
#             return jsonify({
#                 'answer': "I couldn't find relevant information in the document to answer your question.",
#                 'sources': []
#             }), 200
        
#         # Generate answer using Groq
#         result = groq_service.generate_answer(message, relevant_chunks, history)
        
#         return jsonify({
#             'answer': result['answer'],
#             'sources': result['sources'],
#             'file_id': file_id
#         }), 200
        
#     except Exception as e:
#         return jsonify({'error': str(e)}), 500

# @chat_bp.route('/health', methods=['GET'])
# def health_check():
#     """Check if services are running"""
#     groq_status = groq_service.test_connection()
    
#     return jsonify({
#         'status': 'healthy',
#         'groq': 'connected' if groq_status else 'disconnected',
#         'embeddings': 'ready'
#     }), 200







"""
# ============================================
# CHAT ROUTES - COMMENTED OUT
# Routes are now directly in app.py
# ============================================

from flask import Blueprint, request, jsonify
import os

chat_bp = Blueprint('chat', __name__)

@chat_bp.route('/chat', methods=['POST', 'OPTIONS'])
def handle_chat():
    # This route is now handled in app.py
    pass

@chat_bp.route('/health', methods=['GET'])
def health_check():
    # This route is now handled in app.py
    pass
"""

print("⚠️ routes/chat.py is commented out. Using routes from app.py instead.")