import os
import sys
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

# Add the current directory to path so Python can find the services module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import services
from services.document_processor import DocumentProcessor
from services.embedding_service import EmbeddingService
from services.vector_store import VectorStore
from services.groq_service import GroqService

app = Flask(__name__)

# Detect if running on Render
IS_RENDER = os.environ.get('RENDER', False)

# CORS configuration - allow local and Render domains
CORS(app, 
     supports_credentials=True, 
     origins=['http://localhost:5000', 'http://127.0.0.1:5000', 'https://*.onrender.com'],
     allow_headers=['Content-Type', 'Authorization'],
     methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'])

# Configuration - use /tmp/ on Render for ephemeral storage
if IS_RENDER:
    app.config['UPLOAD_FOLDER'] = '/tmp/uploads'
    app.config['VECTOR_STORE_FOLDER'] = '/tmp/vector_store'
    app.config['DATABASE_PATH'] = '/tmp/fileqa_users.db'
else:
    app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads')
    app.config['VECTOR_STORE_FOLDER'] = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'vector_store')
    app.config['DATABASE_PATH'] = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'database', 'users.db')

app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key')
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['SESSION_COOKIE_SECURE'] = IS_RENDER  # Secure in production

# Create required folders
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['VECTOR_STORE_FOLDER'], exist_ok=True)
os.makedirs(os.path.dirname(app.config['DATABASE_PATH']), exist_ok=True)

# Database setup
DATABASE_PATH = app.config['DATABASE_PATH']

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
    print("✅ Database initialized at:", DATABASE_PATH)

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

# Store for uploaded files and vector references
app.user_uploads = {}
app.vector_stores = {}

# Initialize services (lazy loading)
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
print(f"📁 Environment: {'Render' if IS_RENDER else 'Local'}")
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
    return send_from_directory(frontend_folder, 'splash.html')

@app.route('/home')
def serve_home():
    return send_from_directory(frontend_folder, 'index.html')

@app.route('/chat')
def serve_chat():
    return send_from_directory(frontend_folder, 'chat.html')

@app.route('/dashboard')
def serve_dashboard():
    return send_from_directory(frontend_folder, 'dashboard.html')

@app.route('/login')
def serve_login():
    if 'user_id' in session:
        return redirect(url_for('serve_dashboard'))
    return send_from_directory(frontend_folder, 'login.html')

@app.route('/signup')
def serve_signup():
    if 'user_id' in session:
        return redirect(url_for('serve_dashboard'))
    return send_from_directory(frontend_folder, 'signup.html')

@app.route('/css/<path:filename>')
def serve_css(filename):
    return send_from_directory(os.path.join(frontend_folder, 'css'), filename)

@app.route('/js/<path:filename>')
def serve_js(filename):
    return send_from_directory(os.path.join(frontend_folder, 'js'), filename)

@app.route('/assets/<path:filename>')
def serve_assets(filename):
    return send_from_directory(os.path.join(frontend_folder, 'assets'), filename)

# ============================================
# AUTH ENDPOINTS
# ============================================

@app.route('/api/auth/signup', methods=['POST', 'OPTIONS'])
def auth_signup():
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
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
        
        if not username or not email or not password:
            return jsonify({'error': 'Username, email and password required'}), 400
        
        if len(username) < 3:
            return jsonify({'error': 'Username must be at least 3 characters'}), 400
        
        if len(password) < 6:
            return jsonify({'error': 'Password must be at least 6 characters'}), 400
        
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
            
            session['user_id'] = user_id
            session.permanent = True
            
            response = jsonify({
                'message': 'Account created successfully',
                'user': {'id': user_id, 'username': username, 'email': email, 'full_name': full_name}
            })
            response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
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
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
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
            
            load_user_documents_to_memory(user_id)
            
            conn = sqlite3.connect(DATABASE_PATH)
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE id = ?', (user_id,))
            conn.commit()
            conn.close()
            
            response = jsonify({
                'message': 'Login successful',
                'user': {'id': user_id, 'username': username, 'email': user_email, 'full_name': full_name}
            })
            response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
            response.headers.add('Access-Control-Allow-Credentials', 'true')
            return response, 200
        else:
            return jsonify({'error': 'Invalid email or password'}), 401
            
    except Exception as e:
        print(f"❌ Login error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/logout', methods=['POST', 'OPTIONS'])
def auth_logout():
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200
    
    session.clear()
    response = jsonify({'message': 'Logged out successfully'})
    response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response, 200

@app.route('/api/auth/me', methods=['GET', 'OPTIONS'])
def auth_me():
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200
    
    user = get_current_user()
    if user:
        load_user_documents_to_memory(user['id'])
        response = jsonify({'user': user})
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200
    return jsonify({'error': 'Not logged in'}), 401

# ============================================
# DASHBOARD ENDPOINTS
# ============================================

@app.route('/api/dashboard/stats', methods=['GET', 'OPTIONS'])
@login_required
def dashboard_stats():
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200
    
    user = get_current_user()
    documents = get_user_documents(user['id'])
    
    total_documents = len(documents)
    total_chunks = sum(doc['chunks'] for doc in documents)
    recent_documents = documents[:5]
    
    response = jsonify({
        'total_documents': total_documents,
        'total_chunks': total_chunks,
        'documents': recent_documents
    })
    response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response, 200

@app.route('/api/dashboard/documents', methods=['GET', 'OPTIONS'])
@login_required
def dashboard_documents():
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200
    
    user = get_current_user()
    documents = get_user_documents(user['id'])
    response = jsonify({'documents': documents})
    response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response, 200

@app.route('/api/dashboard/document/<file_id>', methods=['DELETE', 'OPTIONS'])
@login_required
def delete_document(file_id):
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'DELETE, OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200
    
    user = get_current_user()
    
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM user_documents WHERE file_id = ?', (file_id,))
    result = cursor.fetchone()
    
    if not result or result[0] != user['id']:
        conn.close()
        return jsonify({'error': 'Document not found'}), 404
    
    cursor.execute('DELETE FROM user_documents WHERE file_id = ?', (file_id,))
    conn.commit()
    conn.close()
    
    vector_store_path = os.path.join(app.config['VECTOR_STORE_FOLDER'], file_id)
    if os.path.exists(f"{vector_store_path}.index"):
        os.remove(f"{vector_store_path}.index")
    if os.path.exists(f"{vector_store_path}.pkl"):
        os.remove(f"{vector_store_path}.pkl")
    
    if file_id in app.vector_stores:
        del app.vector_stores[file_id]
    
    if user['id'] in app.user_uploads and file_id in app.user_uploads[user['id']]:
        del app.user_uploads[user['id']][file_id]
    
    response = jsonify({'message': 'Document deleted successfully'})
    response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response, 200

# ============================================
# UPLOAD ENDPOINT
# ============================================

ALLOWED_EXTENSIONS = {'txt', 'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/api/upload', methods=['POST', 'OPTIONS'])
@login_required
def handle_upload():
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200
    
    user = get_current_user()
    print("\n" + "=" * 40)
    print(f"📤 UPLOAD ENDPOINT HIT - User: {user['username']}")
    print("=" * 40)
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'File type not allowed. Please upload PDF or TXT'}), 400
    
    try:
        file_id = str(uuid.uuid4())
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        print(f"✅ File saved: {file_path}")
        
        print(f"\n🔧 Processing document: {filename}")
        processor = DocumentProcessor()
        text = processor.process_file(file_path)
        print(f"📝 Extracted {len(text)} characters")
        
        chunks = processor.create_chunks(text)
        embedding_service = get_embedding_service()
        chunks_with_embeddings = embedding_service.generate_chunk_embeddings(chunks)
        
        vector_store = VectorStore(embedding_service.embedding_dim)
        vector_store.add_chunks(chunks_with_embeddings)
        
        vector_store_path = os.path.join(app.config['VECTOR_STORE_FOLDER'], file_id)
        vector_store.save(vector_store_path)
        
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
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200
        
    except Exception as e:
        print(f"❌ Upload error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/status/<file_id>', methods=['GET', 'OPTIONS'])
@login_required
def handle_status(file_id):
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200
    
    user = get_current_user()
    
    if user['id'] in app.user_uploads and file_id in app.user_uploads[user['id']]:
        file_info = app.user_uploads[user['id']][file_id]
        response = jsonify({
            'status': file_info.get('status', 'unknown'),
            'file_id': file_id,
            'filename': file_info['filename'],
            'chunks': file_info.get('chunks', 0)
        })
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200
    
    return jsonify({'error': 'File not found'}), 404

# ============================================
# CHAT ENDPOINT
# ============================================

@app.route('/api/chat', methods=['POST', 'OPTIONS'])
@login_required
def handle_chat():
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200
    
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required. Please login.'}), 401
    
    user = get_current_user()
    
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
        
        if not file_id:
            return jsonify({'error': 'No file selected'}), 400
        
        if user['id'] not in app.user_uploads or file_id not in app.user_uploads[user['id']]:
            return jsonify({'error': 'File not found. Please upload again.'}), 404
        
        file_info = app.user_uploads[user['id']][file_id]
        
        if file_id in app.vector_stores:
            vector_store = app.vector_stores[file_id]
        else:
            vector_store_path = os.path.join(app.config['VECTOR_STORE_FOLDER'], file_id)
            if os.path.exists(f"{vector_store_path}.index"):
                embedding_service = get_embedding_service()
                vector_store = VectorStore(embedding_service.embedding_dim)
                vector_store.load(vector_store_path)
                app.vector_stores[file_id] = vector_store
            else:
                return jsonify({'error': 'Document not properly processed'}), 404
        
        embedding_service = get_embedding_service()
        question_embedding = embedding_service.generate_embedding(message)
        relevant_chunks = vector_store.similarity_search(question_embedding, k=5)
        
        if not relevant_chunks:
            return jsonify({
                'answer': "I couldn't find relevant information in the document to answer your question.",
                'sources': []
            }), 200
        
        groq_service = get_groq_service()
        result = groq_service.generate_answer(message, relevant_chunks, data.get('history', []))
        
        response = jsonify({
            'answer': result['answer'],
            'sources': result['sources'],
            'file_id': file_id
        })
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200
        
    except Exception as e:
        print(f"❌ Chat error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# ============================================
# HEALTH ENDPOINTS
# ============================================

@app.route('/api/health', methods=['GET', 'OPTIONS'])
def handle_health():
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response, 200
    
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
    response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response, 200

# ============================================
# SIMPLE HEALTH CHECK (for Render)
# ============================================

@app.route('/healthz')
def healthz():
    """Simple health check for Render - returns 200 if app is running"""
    return jsonify({
        'status': 'healthy',
        'timestamp': time.time(),
        'database': os.path.exists(DATABASE_PATH),
        'session': bool(session.get('user_id'))
    }), 200

# ============================================
# DEBUG ROUTES
# ============================================

@app.route('/api/debug/user-files', methods=['GET'])
@login_required
def debug_user_files():
    user = get_current_user()
    
    if user['id'] not in app.user_uploads or len(app.user_uploads[user['id']]) == 0:
        load_user_documents_to_memory(user['id'])
    
    memory_files = []
    if user['id'] in app.user_uploads:
        for file_id, info in app.user_uploads[user['id']].items():
            memory_files.append({
                'file_id': file_id,
                'filename': info.get('filename'),
                'status': info.get('status'),
                'chunks': info.get('chunks')
            })
    
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT file_id, filename, chunk_count FROM user_documents WHERE user_id = ?', (user['id'],))
    db_files = [{'file_id': row[0], 'filename': row[1], 'chunks': row[2]} for row in cursor.fetchall()]
    conn.close()
    
    response = jsonify({
        'user': user,
        'memory_files': memory_files,
        'database_files': db_files
    })
    response.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response, 200

# ============================================
# ERROR HANDLERS
# ============================================

@app.errorhandler(404)
def handle_not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(413)
def handle_too_large(error):
    return jsonify({'error': 'File too large. Maximum size is 16MB'}), 413

@app.errorhandler(500)
def handle_internal_error(error):
    print(f"❌ Internal error: {error}")
    return jsonify({'error': 'Internal server error'}), 500

# ============================================
# MAIN
# ============================================

if __name__ == '__main__':
    # Get port from environment variable (Render) or use default 5000
    port = int(os.environ.get('PORT', 5000))
    
    print("\n" + "=" * 60)
    print(f"🌐 SERVER RUNNING AT http://localhost:{port}")
    print("=" * 60)
    print("✅ Ready for development!")
    print("=" * 60 + "\n")
    
    # FORCE disable debug mode on Render
    # Check if running on Render
    is_render = os.environ.get('RENDER', False)
    
    if is_render:
        # On Render: NO debug mode, NO auto-reload
        app.run(debug=False, port=port, host='0.0.0.0', use_reloader=False)
    else:
        # Locally: debug mode enabled
        app.run(debug=True, port=port, host='0.0.0.0')