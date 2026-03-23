import os
from flask import Flask, send_from_directory, jsonify, request, session, redirect, url_for
from flask_cors import CORS
from dotenv import load_dotenv
import uuid
from werkzeug.utils import secure_filename
import time
import sqlite3
import bcrypt
from functools import wraps
from datetime import datetime, timedelta

# Load environment variables
load_dotenv()

# Import services
from .services.document_processor import DocumentProcessor
from .services.embedding_service import EmbeddingService
from .services.vector_store import VectorStore
from .services.groq_service import GroqService

app = Flask(__name__)

# Updated CORS configuration - allow credentials from specific origins
CORS(app, 
     supports_credentials=True, 
     origins=['http://localhost:5000', 'http://127.0.0.1:5000'],
     allow_headers=['Content-Type', 'Authorization'],
     methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'])

# Configuration
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads')
app.config['VECTOR_STORE_FOLDER'] = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'vector_store')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key')
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['SESSION_COOKIE_SECURE'] = False  # Set to True in production with HTTPS

# Database setup
DATABASE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'database', 'users.db')
os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)

def init_db():
    """Initialize the database with users table"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # Create users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(50) UNIQUE NOT NULL,
            email VARCHAR(100) UNIQUE NOT NULL,
            password_hash VARCHAR(200) NOT NULL,
            full_name VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        )
    ''')
    
    # Create user_documents table to track user's files
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            file_id VARCHAR(100) NOT NULL,
            filename VARCHAR(255) NOT NULL,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            chunk_count INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(user_id, file_id)
        )
    ''')
    
    conn.commit()
    conn.close()
    print("✅ Database initialized")

# Run database initialization
init_db()

# ============================================
# AUTHENTICATION DECORATORS & HELPERS
# ============================================

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Authentication required. Please login.'}), 401
        return f(*args, **kwargs)
    return decorated_function

def get_current_user():
    """Get current user from session"""
    if 'user_id' in session:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT id, username, email, full_name FROM users WHERE id = ?', (session['user_id'],))
        user = cursor.fetchone()
        conn.close()
        if user:
            return {
                'id': user[0],
                'username': user[1],
                'email': user[2],
                'full_name': user[3]
            }
    return None

def get_user_documents(user_id):
    """Get all documents for a user"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT file_id, filename, uploaded_at, chunk_count 
        FROM user_documents 
        WHERE user_id = ? 
        ORDER BY uploaded_at DESC
    ''', (user_id,))
    documents = cursor.fetchall()
    conn.close()
    return [{'file_id': d[0], 'filename': d[1], 'uploaded_at': d[2], 'chunks': d[3]} for d in documents]

def load_user_documents_to_memory(user_id):
    """Load user's documents from database into app.user_uploads"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT file_id, filename, chunk_count FROM user_documents WHERE user_id = ?', (user_id,))
    documents = cursor.fetchall()
    conn.close()
    
    # Initialize user's upload dict if not exists
    if user_id not in app.user_uploads:
        app.user_uploads[user_id] = {}
    
    # For each document, add to memory
    for file_id, filename, chunk_count in documents:
        # Check if vector store exists
        vector_store_path = os.path.join(app.config['VECTOR_STORE_FOLDER'], file_id)
        vector_store_exists = os.path.exists(f"{vector_store_path}.index")
        
        app.user_uploads[user_id][file_id] = {
            'filename': filename,
            'path': os.path.join(app.config['UPLOAD_FOLDER'], filename),
            'status': 'processed',
            'chunks': chunk_count,
            'vector_store_path': vector_store_path if vector_store_exists else None
        }
        
        # Load vector store into memory if exists
        if vector_store_exists and file_id not in app.vector_stores:
            try:
                embedding_service = get_embedding_service()
                vector_store = VectorStore(embedding_service.embedding_dim)
                vector_store.load(vector_store_path)
                app.vector_stores[file_id] = vector_store
                print(f"📂 Loaded vector store for {filename}")
            except Exception as e:
                print(f"❌ Error loading vector store for {filename}: {e}")
    
    print(f"✅ Loaded {len(documents)} documents for user {user_id}")

# Create required folders
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['VECTOR_STORE_FOLDER'], exist_ok=True)

# Store for uploaded files and vector references (now user-specific)
app.user_uploads = {}  # {user_id: {file_id: {...}}}
app.vector_stores = {}

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
print(f"📁 Database: {DATABASE_PATH}")
print("=" * 60)

# ============================================
# FRONTEND ROUTES
# ============================================

@app.route('/')
def serve_splash():
    """Serve the splash screen (entry point)"""
    return send_from_directory(frontend_folder, 'splash.html')

@app.route('/home')
def serve_home():
    """Serve the original landing page"""
    return send_from_directory(frontend_folder, 'index.html')

@app.route('/chat')
def serve_chat():
    """Serve the chat page (requires login - frontend handles redirect)"""
    return send_from_directory(frontend_folder, 'chat.html')

@app.route('/dashboard')
def serve_dashboard():
    """Serve the dashboard page (requires login - frontend handles redirect)"""
    return send_from_directory(frontend_folder, 'dashboard.html')

@app.route('/login')
def serve_login():
    """Serve the login page - redirect if already logged in"""
    if 'user_id' in session:
        return redirect(url_for('serve_dashboard'))
    return send_from_directory(frontend_folder, 'login.html')

@app.route('/signup')
def serve_signup():
    """Serve the signup page - redirect if already logged in"""
    if 'user_id' in session:
        return redirect(url_for('serve_dashboard'))
    return send_from_directory(frontend_folder, 'signup.html')

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
# API ROUTES - AUTHENTICATION
# ============================================

@app.route('/api/auth/signup', methods=['POST', 'OPTIONS'])
def auth_signup():
    """User registration"""
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', 'http://localhost:5000'))
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200
    
    try:
        data = request.json
        username = data.get('username', '').strip()
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        full_name = data.get('full_name', '').strip()
        
        # Validation
        if not username or not email or not password:
            return jsonify({'error': 'Username, email and password required'}), 400
        
        if len(username) < 3:
            return jsonify({'error': 'Username must be at least 3 characters'}), 400
        
        if len(password) < 6:
            return jsonify({'error': 'Password must be at least 6 characters'}), 400
        
        # Hash password
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                'INSERT INTO users (username, email, password_hash, full_name) VALUES (?, ?, ?, ?)',
                (username, email, password_hash, full_name)
            )
            conn.commit()
            user_id = cursor.lastrowid
            
            # Auto login after signup
            session['user_id'] = user_id
            session.permanent = True
            
            response = jsonify({
                'message': 'Account created successfully',
                'user': {
                    'id': user_id,
                    'username': username,
                    'email': email,
                    'full_name': full_name
                }
            })
            response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', 'http://localhost:5000'))
            response.headers.add('Access-Control-Allow-Credentials', 'true')
            return response, 201
            
        except sqlite3.IntegrityError as e:
            if 'username' in str(e):
                return jsonify({'error': 'Username already exists'}), 400
            elif 'email' in str(e):
                return jsonify({'error': 'Email already registered'}), 400
            return jsonify({'error': 'User already exists'}), 400
        finally:
            conn.close()
            
    except Exception as e:
        print(f"❌ Signup error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/login', methods=['POST', 'OPTIONS'])
def auth_login():
    """User login"""
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', 'http://localhost:5000'))
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200
    
    try:
        data = request.json
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({'error': 'Email and password required'}), 400
        
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT id, username, email, password_hash, full_name FROM users WHERE email = ?', (email,))
        user = cursor.fetchone()
        conn.close()
        
        if not user:
            return jsonify({'error': 'Invalid email or password'}), 401
        
        user_id, username, user_email, password_hash, full_name = user
        
        if bcrypt.checkpw(password.encode('utf-8'), password_hash):
            session['user_id'] = user_id
            session.permanent = True
            
            # Load user documents into memory on login
            load_user_documents_to_memory(user_id)
            
            # Update last login
            conn = sqlite3.connect(DATABASE_PATH)
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?', (user_id,))
            conn.commit()
            conn.close()
            
            response = jsonify({
                'message': 'Login successful',
                'user': {
                    'id': user_id,
                    'username': username,
                    'email': user_email,
                    'full_name': full_name
                }
            })
            response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', 'http://localhost:5000'))
            response.headers.add('Access-Control-Allow-Credentials', 'true')
            return response, 200
        else:
            return jsonify({'error': 'Invalid email or password'}), 401
            
    except Exception as e:
        print(f"❌ Login error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/logout', methods=['POST', 'OPTIONS'])
def auth_logout():
    """User logout"""
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', 'http://localhost:5000'))
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200
    
    session.clear()
    response = jsonify({'message': 'Logged out successfully'})
    response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', 'http://localhost:5000'))
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response, 200

@app.route('/api/auth/me', methods=['GET', 'OPTIONS'])
def auth_me():
    """Get current logged in user"""
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', 'http://localhost:5000'))
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200
    
    user = get_current_user()
    if user:
        # Load user documents into memory
        load_user_documents_to_memory(user['id'])
        
        response = jsonify({'user': user})
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', 'http://localhost:5000'))
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200
    return jsonify({'error': 'Not logged in'}), 401

# ============================================
# API ROUTES - DASHBOARD
# ============================================

@app.route('/api/dashboard/stats', methods=['GET', 'OPTIONS'])
@login_required
def dashboard_stats():
    """Get user statistics"""
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', 'http://localhost:5000'))
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200
    
    user = get_current_user()
    documents = get_user_documents(user['id'])
    
    # Calculate stats
    total_documents = len(documents)
    total_chunks = sum(doc['chunks'] for doc in documents)
    
    # Get recent documents (last 5)
    recent_documents = documents[:5]
    
    response = jsonify({
        'total_documents': total_documents,
        'total_chunks': total_chunks,
        'documents': recent_documents
    })
    response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', 'http://localhost:5000'))
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response, 200

@app.route('/api/dashboard/documents', methods=['GET', 'OPTIONS'])
@login_required
def dashboard_documents():
    """Get all user documents"""
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', 'http://localhost:5000'))
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200
    
    user = get_current_user()
    documents = get_user_documents(user['id'])
    response = jsonify({'documents': documents})
    response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', 'http://localhost:5000'))
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response, 200

@app.route('/api/dashboard/document/<file_id>', methods=['DELETE', 'OPTIONS'])
@login_required
def delete_document(file_id):
    """Delete a user document"""
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', 'http://localhost:5000'))
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'DELETE, OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200
    
    user = get_current_user()
    
    # Check if document belongs to user
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM user_documents WHERE file_id = ?', (file_id,))
    result = cursor.fetchone()
    
    if not result or result[0] != user['id']:
        conn.close()
        return jsonify({'error': 'Document not found'}), 404
    
    # Delete from database
    cursor.execute('DELETE FROM user_documents WHERE file_id = ?', (file_id,))
    conn.commit()
    conn.close()
    
    # Delete vector store
    vector_store_path = os.path.join(app.config['VECTOR_STORE_FOLDER'], file_id)
    if os.path.exists(f"{vector_store_path}.index"):
        os.remove(f"{vector_store_path}.index")
    if os.path.exists(f"{vector_store_path}.pkl"):
        os.remove(f"{vector_store_path}.pkl")
    
    # Remove from app memory
    if file_id in app.vector_stores:
        del app.vector_stores[file_id]
    
    if user['id'] in app.user_uploads and file_id in app.user_uploads[user['id']]:
        del app.user_uploads[user['id']][file_id]
    
    response = jsonify({'message': 'Document deleted successfully'})
    response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', 'http://localhost:5000'))
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response, 200

# ============================================
# API ROUTES - UPLOAD (Updated with user tracking)
# ============================================

ALLOWED_EXTENSIONS = {'txt', 'pdf'}

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/api/upload', methods=['POST', 'OPTIONS'])
@login_required
def handle_upload():
    """Handle file upload and processing"""
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', 'http://localhost:5000'))
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200
    
    user = get_current_user()
    print("\n" + "=" * 40)
    print(f"📤 UPLOAD ENDPOINT HIT - User: {user['username']}")
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
        
        # Store reference (user-specific)
        if user['id'] not in app.user_uploads:
            app.user_uploads[user['id']] = {}
        
        app.user_uploads[user['id']][file_id] = {
            'filename': filename,
            'path': file_path,
            'status': 'processed',
            'upload_time': time.time(),
            'chunks': len(chunks),
            'vector_store_path': vector_store_path
        }
        
        app.vector_stores[file_id] = vector_store
        
        # Save to database
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO user_documents (user_id, file_id, filename, chunk_count)
            VALUES (?, ?, ?, ?)
        ''', (user['id'], file_id, filename, len(chunks)))
        conn.commit()
        conn.close()
        
        print(f"✅ Document processed successfully! {len(chunks)} chunks created")
        
        response = jsonify({
            'message': 'File uploaded and processed successfully',
            'file_id': file_id,
            'filename': filename,
            'chunks': len(chunks),
            'status': 'processed'
        })
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', 'http://localhost:5000'))
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200
        
    except Exception as e:
        print(f"❌ Upload error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/status/<file_id>', methods=['GET', 'OPTIONS'])
@login_required
def handle_status(file_id):
    """Get file processing status"""
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', 'http://localhost:5000'))
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200
    
    user = get_current_user()
    
    # Check if file belongs to user
    if user['id'] in app.user_uploads and file_id in app.user_uploads[user['id']]:
        file_info = app.user_uploads[user['id']][file_id]
        response = jsonify({
            'status': file_info.get('status', 'unknown'),
            'file_id': file_id,
            'filename': file_info['filename'],
            'chunks': file_info.get('chunks', 0)
        })
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', 'http://localhost:5000'))
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200
    
    return jsonify({'error': 'File not found'}), 404

# ============================================
# API ROUTES - CHAT (Updated with user-specific files)
# ============================================

@app.route('/api/chat', methods=['POST', 'OPTIONS'])
@login_required
def handle_chat():
    """Handle chat messages with RAG"""
    # Handle preflight OPTIONS request
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', 'http://localhost:5000'))
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200
    
    # Check if user is logged in
    if 'user_id' not in session:
        print("❌ No user in session")
        return jsonify({'error': 'Authentication required. Please login.'}), 401
    
    user = get_current_user()
    
    # Load user documents if not in memory
    if user['id'] not in app.user_uploads or len(app.user_uploads[user['id']]) == 0:
        print(f"📂 Loading documents for user {user['id']} from database")
        load_user_documents_to_memory(user['id'])
    
    try:
        data = request.json
        print("\n" + "=" * 40)
        print(f"💬 CHAT REQUEST - User: {user['username']}")
        print("=" * 40)
        
        if not data or 'message' not in data:
            return jsonify({'error': 'No message provided'}), 400
        
        message = data['message']
        file_id = data.get('file_id')
        
        print(f"📝 Question: {message}")
        print(f"🆔 File ID: {file_id}")
        
        if not file_id:
            return jsonify({'error': 'No file selected'}), 400
        
        # Debug: Print what's available
        print(f"🔍 Checking user {user['id']} uploads: {list(app.user_uploads.get(user['id'], {}).keys())}")
        
        # Check if file belongs to user
        if user['id'] not in app.user_uploads or file_id not in app.user_uploads[user['id']]:
            return jsonify({'error': 'File not found. Please upload again.'}), 404
        
        file_info = app.user_uploads[user['id']][file_id]
        print(f"✅ File found: {file_info['filename']}")
        
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
        
        # Add CORS headers to response
        response = jsonify({
            'answer': result['answer'],
            'sources': result['sources'],
            'file_id': file_id
        })
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', 'http://localhost:5000'))
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200
        
    except Exception as e:
        print(f"❌ Chat error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# ============================================
# API ROUTES - HEALTH
# ============================================

@app.route('/api/health', methods=['GET', 'OPTIONS'])
def handle_health():
    """Health check endpoint"""
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', 'http://localhost:5000'))
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200
    
    # Test Groq connection
    groq_ok = False
    try:
        groq_service = get_groq_service()
        groq_ok = groq_service.test_connection()
    except:
        pass
    
    response = jsonify({
        'status': 'healthy',
        'groq_connected': groq_ok,
        'database': os.path.exists(DATABASE_PATH),
        'session': bool(session.get('user_id'))
    })
    response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', 'http://localhost:5000'))
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response, 200

# ============================================
# DEBUG ROUTES - For troubleshooting
# ============================================

@app.route('/api/debug/user-files', methods=['GET'])
@login_required
def debug_user_files():
    """Debug endpoint to see what files are associated with user"""
    user = get_current_user()
    
    # Load from database if not in memory
    if user['id'] not in app.user_uploads or len(app.user_uploads[user['id']]) == 0:
        load_user_documents_to_memory(user['id'])
    
    # Get from memory
    memory_files = []
    if user['id'] in app.user_uploads:
        for file_id, info in app.user_uploads[user['id']].items():
            memory_files.append({
                'file_id': file_id,
                'filename': info.get('filename'),
                'status': info.get('status'),
                'chunks': info.get('chunks')
            })
    
    # Get from database
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT file_id, filename, chunk_count FROM user_documents WHERE user_id = ?', (user['id'],))
    db_files = [{'file_id': row[0], 'filename': row[1], 'chunks': row[2]} for row in cursor.fetchall()]
    conn.close()
    
    return jsonify({
        'user': user,
        'memory_files': memory_files,
        'database_files': db_files
    }), 200

@app.route('/api/debug/upload/<file_id>', methods=['GET'])
@login_required
def debug_upload(file_id):
    """Debug endpoint to check a specific file"""
    user = get_current_user()
    
    # Load from database if not in memory
    if user['id'] not in app.user_uploads or len(app.user_uploads[user['id']]) == 0:
        load_user_documents_to_memory(user['id'])
    
    # Check memory
    in_memory = False
    file_info = None
    if user['id'] in app.user_uploads and file_id in app.user_uploads[user['id']]:
        in_memory = True
        file_info = app.user_uploads[user['id']][file_id]
    
    # Check database
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM user_documents WHERE user_id = ? AND file_id = ?', (user['id'], file_id))
    db_record = cursor.fetchone()
    conn.close()
    
    # Check vector store
    vector_store_path = os.path.join(app.config['VECTOR_STORE_FOLDER'], file_id)
    vector_store_exists = os.path.exists(f"{vector_store_path}.index") and os.path.exists(f"{vector_store_path}.pkl")
    
    return jsonify({
        'file_id': file_id,
        'in_memory': in_memory,
        'file_info': file_info,
        'database_record': db_record,
        'vector_store_exists': vector_store_exists,
        'vector_store_path': vector_store_path
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
    print(f"❌ Internal error: {error}")
    return jsonify({'error': 'Internal server error'}), 500

# ============================================
# MAIN
# ============================================
# Debug: Print all registered routes
print("\n📋 REGISTERED ROUTES:")
for rule in app.url_map.iter_rules():
    print(f"   {rule.endpoint}: {rule.methods} -> {rule.rule}")

if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("🌐 SERVER RUNNING AT http://localhost:5000")
    print("=" * 60)
    print("📝 Available endpoints:")
    print("   - GET  /                  - Splash screen (entry point)")
    print("   - GET  /home              - Landing page")
    print("   - GET  /chat              - Chat page")
    print("   - GET  /dashboard         - Dashboard page")
    print("   - GET  /login             - Login page")
    print("   - GET  /signup            - Signup page")
    print("")
    print("🔐 AUTH ENDPOINTS:")
    print("   - POST /api/auth/signup   - Create account")
    print("   - POST /api/auth/login    - Login")
    print("   - POST /api/auth/logout   - Logout")
    print("   - GET  /api/auth/me       - Get current user")
    print("")
    print("📊 DASHBOARD ENDPOINTS:")
    print("   - GET  /api/dashboard/stats      - User stats")
    print("   - GET  /api/dashboard/documents  - User documents")
    print("   - DELETE /api/dashboard/document/<id> - Delete document")
    print("")
    print("💬 CORE ENDPOINTS (require login):")
    print("   - POST /api/upload         - Upload file")
    print("   - POST /api/chat           - Send message")
    print("   - GET  /api/status/<id>    - File status")
    print("")
    print("🐛 DEBUG ENDPOINTS:")
    print("   - GET  /api/debug/user-files    - List user files")
    print("   - GET  /api/debug/upload/<id>   - Check specific file")
    print("")
    print("✅ Authentication System Ready!")
    print("   - User registration with bcrypt hashing")
    print("   - Session-based authentication")
    print("   - User-specific document storage")
    print("   - Auto login after signup")
    print("=" * 60 + "\n")
    
    app.run(debug=True, port=5000, host='0.0.0.0')