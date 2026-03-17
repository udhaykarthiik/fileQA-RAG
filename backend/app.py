import os
from flask import Flask, send_from_directory, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
import uuid
from werkzeug.utils import secure_filename

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app, supports_credentials=True)

# Configuration
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key')

# Create required folders
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'vector_store'), exist_ok=True)

# Store for uploaded files and vector references
app.uploaded_files = {}
app.vector_stores = {}

# Get frontend path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
frontend_folder = os.path.join(project_root, 'frontend')

print("=" * 60)
print("🚀 FileQA Chatbot Starting...")
print(f"📁 Frontend: {frontend_folder}")
print(f"📁 Uploads: {app.config['UPLOAD_FOLDER']}")
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
    """Handle file upload"""
    # Handle preflight OPTIONS request
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST')
        return response, 200
    
    print("📤 Upload endpoint hit!")
    
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
            'status': 'uploaded'
        }
        
        return jsonify({
            'message': 'File uploaded successfully',
            'file_id': file_id,
            'filename': filename,
            'chunks': 0
        }), 200
        
    except Exception as e:
        print(f"❌ Upload error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/status/<file_id>', methods=['GET', 'OPTIONS'])
def handle_status(file_id):
    """Get file processing status"""
    # Handle preflight OPTIONS request
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'GET')
        return response, 200
    
    if file_id in app.uploaded_files:
        return jsonify({
            'status': 'processed',
            'file_id': file_id,
            'filename': app.uploaded_files[file_id]['filename']
        }), 200
    
    return jsonify({'error': 'File not found'}), 404

# ============================================
# API ROUTES - CHAT
# ============================================

@app.route('/api/chat', methods=['POST', 'OPTIONS'])
def handle_chat():
    """Handle chat messages"""
    # Handle preflight OPTIONS request
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST')
        return response, 200
    
    try:
        data = request.json
        print(f"💬 Chat request received")
        
        if not data or 'message' not in data:
            return jsonify({'error': 'No message provided'}), 400
        
        message = data['message']
        file_id = data.get('file_id')
        
        print(f"   Message: {message[:50]}...")
        print(f"   File ID: {file_id}")
        
        if not file_id:
            return jsonify({'error': 'No file selected'}), 400
        
        # Check if file exists
        if file_id not in app.uploaded_files:
            return jsonify({'error': 'File not found. Please upload again.'}), 404
        
        filename = app.uploaded_files[file_id]['filename']
        
        # Simple response for now (will be replaced with actual RAG)
        response = {
            'answer': f"I see you're asking about '{message}'. The document '{filename}' has been uploaded successfully. The RAG pipeline will be fully implemented in the next step!",
            'sources': [
                {'text': f'Source: {filename}', 'score': 0.95}
            ],
            'file_id': file_id
        }
        
        return jsonify(response), 200
        
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
    
    return jsonify({
        'status': 'healthy',
        'uploads': len(app.uploaded_files),
        'vector_stores': len(app.vector_stores)
    }), 200

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
    return jsonify({'error': 'Internal server error'}), 500

# ============================================
# MAIN
# ============================================

if __name__ == '__main__':
    print("\n🌐 Server running at http://localhost:5000")
    print("📝 Available endpoints:")
    print("   - GET  /              - Landing page")
    print("   - GET  /chat          - Chat page")
    print("   - POST /api/upload    - Upload file")
    print("   - POST /api/chat      - Send message")
    print("   - GET  /api/health    - Health check")
    print("\n✅ Ready to accept connections!\n")
    app.run(debug=True, port=5000, host='0.0.0.0')