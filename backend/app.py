import os
from flask import Flask, send_from_directory, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
import uuid
from werkzeug.utils import secure_filename
import time

# Load environment variables
load_dotenv()

# Import services
from services.document_processor import DocumentProcessor
from services.embedding_service import EmbeddingService
from services.vector_store import VectorStore
from services.groq_service import GroqService

app = Flask(__name__)
CORS(app, supports_credentials=True)

# Configuration
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads')
app.config['VECTOR_STORE_FOLDER'] = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'vector_store')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key')

# Create required folders
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['VECTOR_STORE_FOLDER'], exist_ok=True)

# Store for uploaded files and vector references
app.uploaded_files = {}
app.vector_stores = {}
app.processed_files = {}

# Initialize services (lazy loading to save memory)
app.embedding_service = None
app.groq_service = None

def get_embedding_service():
    """Lazy load embedding service"""
    if app.embedding_service is None:
        print("🔄 Initializing embedding service...")
        app.embedding_service = EmbeddingService()
    return app.embedding_service

def get_groq_service():
    """Lazy load groq service"""
    if app.groq_service is None:
        print("🔄 Initializing Groq service...")
        app.groq_service = GroqService()
    return app.groq_service

# Get frontend path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
frontend_folder = os.path.join(project_root, 'frontend')

print("=" * 60)
print("🚀 FileQA Chatbot Starting...")
print(f"📁 Frontend: {frontend_folder}")
print(f"📁 Uploads: {app.config['UPLOAD_FOLDER']}")
print(f"📁 Vector Store: {app.config['VECTOR_STORE_FOLDER']}")
print("=" * 60)

# ============================================
# FRONTEND ROUTES
# ============================================

@app.route('/')
def serve_index():
    """Serve the landing page"""
    return send_from_directory(frontend_folder, 'index.html')

@app.route('/chat')
def serve_chat():
    """Serve the chat page"""
    return send_from_directory(frontend_folder, 'chat.html')

# Serve static files
@app.route('/css/<path:filename>')
def serve_css(filename):
    """Serve CSS files"""
    return send_from_directory(os.path.join(frontend_folder, 'css'), filename)

@app.route('/js/<path:filename>')
def serve_js(filename):
    """Serve JavaScript files"""
    return send_from_directory(os.path.join(frontend_folder, 'js'), filename)

@app.route('/assets/<path:filename>')
def serve_assets(filename):
    """Serve asset files"""
    return send_from_directory(os.path.join(frontend_folder, 'assets'), filename)

# ============================================
# API ROUTES - UPLOAD
# ============================================

ALLOWED_EXTENSIONS = {'txt', 'pdf'}

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/api/upload', methods=['POST', 'OPTIONS'])
def handle_upload():
    """Handle file upload and processing"""
    # Handle preflight OPTIONS request
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST')
        return response, 200
    
    print("\n" + "=" * 40)
    print("📤 UPLOAD ENDPOINT HIT")
    print("=" * 40)
    
    if 'file' not in request.files:
        print("❌ No file in request")
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    print(f"📄 File received: {file.filename}")
    
    if file.filename == '':
        print("❌ Empty filename")
        return jsonify({'error': 'No file selected'}), 400
    
    if not allowed_file(file.filename):
        print(f"❌ File type not allowed: {file.filename}")
        return jsonify({'error': 'File type not allowed. Please upload PDF or TXT'}), 400
    
    try:
        # Generate unique file ID
        file_id = str(uuid.uuid4())
        filename = secure_filename(file.filename)
        
        # Save file
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        print(f"✅ File saved: {file_path}")
        
        # Store file info
        app.uploaded_files[file_id] = {
            'filename': filename,
            'path': file_path,
            'status': 'processing',
            'upload_time': time.time()
        }
        
        # Start processing in background (for demo, we'll process synchronously)
        # In production, you'd want to do this in a background task
        try:
            # Process document
            print(f"\n🔧 Processing document: {filename}")
            processor = DocumentProcessor()
            
            # Extract text
            text = processor.process_file(file_path)
            print(f"📝 Extracted {len(text)} characters")
            
            # Create chunks
            chunks = processor.create_chunks(text)
            
            # Generate embeddings
            embedding_service = get_embedding_service()
            chunks_with_embeddings = embedding_service.generate_chunk_embeddings(chunks)
            
            # Create vector store
            vector_store = VectorStore(embedding_service.embedding_dim)
            vector_store.add_chunks(chunks_with_embeddings)
            
            # Save vector store
            vector_store_path = os.path.join(app.config['VECTOR_STORE_FOLDER'], file_id)
            vector_store.save(vector_store_path)
            
            # Store reference
            app.vector_stores[file_id] = vector_store
            app.uploaded_files[file_id]['status'] = 'processed'
            app.uploaded_files[file_id]['chunks'] = len(chunks)
            app.uploaded_files[file_id]['vector_store_path'] = vector_store_path
            
            print(f"✅ Document processed successfully! {len(chunks)} chunks created")
            
        except Exception as e:
            print(f"❌ Error processing document: {str(e)}")
            app.uploaded_files[file_id]['status'] = 'error'
            app.uploaded_files[file_id]['error'] = str(e)
        
        return jsonify({
            'message': 'File uploaded and processed successfully',
            'file_id': file_id,
            'filename': filename,
            'chunks': app.uploaded_files[file_id].get('chunks', 0),
            'status': app.uploaded_files[file_id]['status']
        }), 200
        
    except Exception as e:
        print(f"❌ Upload error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/status/<file_id>', methods=['GET', 'OPTIONS'])
def handle_status(file_id):
    """Get file processing status"""
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'GET')
        return response, 200
    
    if file_id in app.uploaded_files:
        file_info = app.uploaded_files[file_id]
        return jsonify({
            'status': file_info.get('status', 'unknown'),
            'file_id': file_id,
            'filename': file_info['filename'],
            'chunks': file_info.get('chunks', 0)
        }), 200
    
    return jsonify({'error': 'File not found'}), 404

# ============================================
# API ROUTES - CHAT
# ============================================

@app.route('/api/chat', methods=['POST', 'OPTIONS'])
def handle_chat():
    """Handle chat messages with RAG"""
    # Handle preflight OPTIONS request
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST')
        return response, 200
    
    try:
        data = request.json
        print("\n" + "=" * 40)
        print("💬 CHAT REQUEST RECEIVED")
        print("=" * 40)
        
        if not data or 'message' not in data:
            return jsonify({'error': 'No message provided'}), 400
        
        message = data['message']
        file_id = data.get('file_id')
        
        print(f"📝 Question: {message}")
        print(f"🆔 File ID: {file_id}")
        
        if not file_id:
            return jsonify({'error': 'No file selected'}), 400
        
        # Check if file exists
        if file_id not in app.uploaded_files:
            return jsonify({'error': 'File not found. Please upload again.'}), 404
        
        file_info = app.uploaded_files[file_id]
        
        # Check if file is still processing
        if file_info.get('status') == 'processing':
            return jsonify({
                'answer': "⏳ Your document is still being processed. Please wait a moment and try again.",
                'sources': []
            }), 200
        
        if file_info.get('status') == 'error':
            return jsonify({
                'answer': f"❌ There was an error processing your document: {file_info.get('error', 'Unknown error')}",
                'sources': []
            }), 200
        
        # Get or load vector store
        if file_id in app.vector_stores:
            vector_store = app.vector_stores[file_id]
            print("📂 Using cached vector store")
        else:
            # Load from disk
            vector_store_path = os.path.join(app.config['VECTOR_STORE_FOLDER'], file_id)
            if os.path.exists(f"{vector_store_path}.index"):
                print("📂 Loading vector store from disk")
                embedding_service = get_embedding_service()
                vector_store = VectorStore(embedding_service.embedding_dim)
                vector_store.load(vector_store_path)
                app.vector_stores[file_id] = vector_store
            else:
                return jsonify({'error': 'Document not properly processed'}), 404
        
        # Generate embedding for question
        embedding_service = get_embedding_service()
        question_embedding = embedding_service.generate_embedding(message)
        
        # Search for relevant chunks
        relevant_chunks = vector_store.similarity_search(question_embedding, k=5)
        
        if not relevant_chunks:
            return jsonify({
                'answer': "I couldn't find relevant information in the document to answer your question.",
                'sources': []
            }), 200
        
        # Generate answer using Groq
        groq_service = get_groq_service()
        result = groq_service.generate_answer(message, relevant_chunks, data.get('history', []))
        
        print(f"✅ Answer generated successfully")
        
        return jsonify({
            'answer': result['answer'],
            'sources': result['sources'],
            'file_id': file_id
        }), 200
        
    except Exception as e:
        print(f"❌ Chat error: {str(e)}")
        return jsonify({'error': str(e)}), 500

# ============================================
# API ROUTES - HEALTH
# ============================================

@app.route('/api/health', methods=['GET', 'OPTIONS'])
def handle_health():
    """Health check endpoint"""
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'GET')
        return response, 200
    
    # Test Groq connection
    groq_ok = False
    try:
        groq_service = get_groq_service()
        groq_ok = groq_service.test_connection()
    except:
        pass
    
    return jsonify({
        'status': 'healthy',
        'groq_connected': groq_ok,
        'uploads': len(app.uploaded_files),
        'vector_stores': len(app.vector_stores),
        'processed_files': len([f for f in app.uploaded_files.values() if f.get('status') == 'processed'])
    }), 200

# ============================================
# API ROUTES - DEBUG (Optional)
# ============================================

@app.route('/api/files', methods=['GET'])
def list_files():
    """List all uploaded files (for debugging)"""
    files = []
    for file_id, info in app.uploaded_files.items():
        files.append({
            'file_id': file_id,
            'filename': info['filename'],
            'status': info.get('status', 'unknown'),
            'chunks': info.get('chunks', 0)
        })
    return jsonify(files), 200

# ============================================
# ERROR HANDLERS
# ============================================

@app.errorhandler(404)
def handle_not_found(error):
    """Handle 404 errors"""
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(413)
def handle_too_large(error):
    """Handle file too large errors"""
    return jsonify({'error': 'File too large. Maximum size is 16MB'}), 413

@app.errorhandler(500)
def handle_internal_error(error):
    """Handle 500 errors"""
    print(f"❌ Internal error: {error}")
    return jsonify({'error': 'Internal server error'}), 500

# ============================================
# MAIN
# ============================================

if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("🌐 SERVER RUNNING AT http://localhost:5000")
    print("=" * 60)
    print("📝 Available endpoints:")
    print("   - GET  /              - Landing page")
    print("   - GET  /chat          - Chat page")
    print("   - POST /api/upload    - Upload file")
    print("   - POST /api/chat      - Send message")
    print("   - GET  /api/health    - Health check")
    print("   - GET  /api/files     - List files (debug)")
    print("\n✅ RAG Pipeline Ready!")
    print("   - PDF text extraction")
    print("   - Semantic chunking")
    print("   - Vector embeddings")
    print("   - Groq LLM integration")
    print("=" * 60 + "\n")
    
    app.run(debug=True, port=5000, host='0.0.0.0')