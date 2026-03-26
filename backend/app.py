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

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.document_processor import DocumentProcessor
from services.embedding_service import EmbeddingService
from services.vector_store import VectorStore
from services.groq_service import GroqService

app = Flask(__name__)

IS_RENDER = os.environ.get('RENDER', False)

CORS(app,
     supports_credentials=True,
     origins=['http://localhost:5000', 'http://127.0.0.1:5000', 'https://*.onrender.com'],
     allow_headers=['Content-Type', 'Authorization'],
     methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'])

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
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['SESSION_COOKIE_SECURE'] = bool(IS_RENDER)
app.config['SESSION_COOKIE_SAMESITE'] = 'None' if IS_RENDER else 'Lax'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['VECTOR_STORE_FOLDER'], exist_ok=True)
os.makedirs(os.path.dirname(app.config['DATABASE_PATH']), exist_ok=True)

DATABASE_PATH = app.config['DATABASE_PATH']


def init_db():
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
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


init_db()

# ============================================
# AUTH DECORATORS & HELPERS
# ============================================

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Authentication required. Please login.'}), 401
        return f(*args, **kwargs)
    return decorated_function


def get_current_user():
    if 'user_id' in session:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT id, username, email, full_name FROM users WHERE id = ?', (session['user_id'],))
        user = cursor.fetchone()
        conn.close()
        if user:
            return {'id': user[0], 'username': user[1], 'email': user[2], 'full_name': user[3]}
    return None


def get_user_documents(user_id):
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
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT file_id, filename, chunk_count FROM user_documents WHERE user_id = ?', (user_id,))
    documents = cursor.fetchall()
    conn.close()

    if user_id not in app.user_uploads:
        app.user_uploads[user_id] = {}

    for file_id, filename, chunk_count in documents:
        vector_store_path = os.path.join(app.config['VECTOR_STORE_FOLDER'], file_id)
        vector_store_exists = os.path.exists(f"{vector_store_path}.index")

        app.user_uploads[user_id][file_id] = {
            'filename': filename,
            'path': os.path.join(app.config['UPLOAD_FOLDER'], filename),
            'status': 'processed',
            'chunks': chunk_count,
            'vector_store_path': vector_store_path if vector_store_exists else None
        }

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


# In-memory stores
app.user_uploads = {}
app.vector_stores = {}
app.embedding_service = None
app.groq_service = None


def get_embedding_service():
    if app.embedding_service is None:
        print("🔄 Initializing embedding service...")
        app.embedding_service = EmbeddingService()
    return app.embedding_service


def get_groq_service():
    if app.groq_service is None:
        print("🔄 Initializing Groq service...")
        app.groq_service = GroqService()
    return app.groq_service


current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
frontend_folder = os.path.join(project_root, 'frontend')

print("=" * 60)
print("🚀 RAG Flow Chatbot Starting...")
print(f"📁 Environment: {'Render' if IS_RENDER else 'Local'}")
print(f"📁 Frontend:    {frontend_folder}")
print(f"📁 Uploads:     {app.config['UPLOAD_FOLDER']}")
print(f"📁 Vector Store:{app.config['VECTOR_STORE_FOLDER']}")
print(f"📁 Database:    {DATABASE_PATH}")
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

def _cors_preflight():
    """Return a preflight OK response"""
    res = jsonify({'status': 'ok'})
    res.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
    res.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    res.headers.add('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
    res.headers.add('Access-Control-Allow-Credentials', 'true')
    return res, 200


def _cors_response(data, status=200):
    """Wrap a jsonify response with CORS headers"""
    res = jsonify(data)
    res.headers.add('Access-Control-Allow-Origin', request.headers.get('Origin', '*'))
    res.headers.add('Access-Control-Allow-Credentials', 'true')
    return res, status


@app.route('/api/auth/signup', methods=['POST', 'OPTIONS'])
def auth_signup():
    if request.method == 'OPTIONS':
        return _cors_preflight()
    try:
        data = request.json
        username = data.get('username', '').strip()
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        full_name = data.get('full_name', '').strip()

        if not username or not email or not password:
            return _cors_response({'error': 'Username, email and password required'}, 400)
        if len(username) < 3:
            return _cors_response({'error': 'Username must be at least 3 characters'}, 400)
        if len(password) < 6:
            return _cors_response({'error': 'Password must be at least 6 characters'}, 400)

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
            return _cors_response({
                'message': 'Account created successfully',
                'user': {'id': user_id, 'username': username, 'email': email, 'full_name': full_name}
            }, 201)
        except sqlite3.IntegrityError as e:
            if 'username' in str(e):
                return _cors_response({'error': 'Username already exists'}, 400)
            elif 'email' in str(e):
                return _cors_response({'error': 'Email already registered'}, 400)
            return _cors_response({'error': 'User already exists'}, 400)
        finally:
            conn.close()
    except Exception as e:
        print(f"❌ Signup error: {e}")
        return _cors_response({'error': str(e)}, 500)


@app.route('/api/auth/login', methods=['POST', 'OPTIONS'])
def auth_login():
    if request.method == 'OPTIONS':
        return _cors_preflight()
    try:
        data = request.json
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')

        if not email or not password:
            return _cors_response({'error': 'Email and password required'}, 400)

        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT id, username, email, password_hash, full_name FROM users WHERE email = ?', (email,))
        user = cursor.fetchone()
        conn.close()

        if not user:
            return _cors_response({'error': 'Invalid email or password'}, 401)

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

            return _cors_response({
                'message': 'Login successful',
                'user': {'id': user_id, 'username': username, 'email': user_email, 'full_name': full_name}
            })
        return _cors_response({'error': 'Invalid email or password'}, 401)
    except Exception as e:
        print(f"❌ Login error: {e}")
        return _cors_response({'error': str(e)}, 500)


@app.route('/api/auth/logout', methods=['POST', 'OPTIONS'])
def auth_logout():
    if request.method == 'OPTIONS':
        return _cors_preflight()
    session.clear()
    return _cors_response({'message': 'Logged out successfully'})


@app.route('/api/auth/me', methods=['GET', 'OPTIONS'])
def auth_me():
    if request.method == 'OPTIONS':
        return _cors_preflight()
    user = get_current_user()
    if user:
        load_user_documents_to_memory(user['id'])
        return _cors_response({'user': user})
    return _cors_response({'error': 'Not logged in'}, 401)

# ============================================
# DASHBOARD ENDPOINTS
# ============================================

@app.route('/api/dashboard/stats', methods=['GET', 'OPTIONS'])
@login_required
def dashboard_stats():
    if request.method == 'OPTIONS':
        return _cors_preflight()
    user = get_current_user()
    documents = get_user_documents(user['id'])
    return _cors_response({
        'total_documents': len(documents),
        'total_chunks': sum(d['chunks'] for d in documents),
        'documents': documents[:5]
    })


@app.route('/api/dashboard/documents', methods=['GET', 'OPTIONS'])
@login_required
def dashboard_documents():
    if request.method == 'OPTIONS':
        return _cors_preflight()
    user = get_current_user()
    return _cors_response({'documents': get_user_documents(user['id'])})


@app.route('/api/dashboard/document/<file_id>', methods=['DELETE', 'OPTIONS'])
@login_required
def delete_document(file_id):
    if request.method == 'OPTIONS':
        return _cors_preflight()

    user = get_current_user()
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM user_documents WHERE file_id = ?', (file_id,))
    result = cursor.fetchone()

    if not result or result[0] != user['id']:
        conn.close()
        return _cors_response({'error': 'Document not found'}, 404)

    cursor.execute('DELETE FROM user_documents WHERE file_id = ?', (file_id,))
    conn.commit()
    conn.close()

    for ext in ['.index', '.pkl']:
        path = os.path.join(app.config['VECTOR_STORE_FOLDER'], file_id) + ext
        if os.path.exists(path):
            os.remove(path)

    app.vector_stores.pop(file_id, None)
    if user['id'] in app.user_uploads:
        app.user_uploads[user['id']].pop(file_id, None)

    return _cors_response({'message': 'Document deleted successfully'})

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
        return _cors_preflight()

    user = get_current_user()
    print(f"\n📤 UPLOAD — User: {user['username']}")

    if 'file' not in request.files:
        return _cors_response({'error': 'No file provided'}, 400)

    file = request.files['file']
    if file.filename == '':
        return _cors_response({'error': 'No file selected'}, 400)
    if not allowed_file(file.filename):
        return _cors_response({'error': 'Only PDF or TXT files allowed'}, 400)

    try:
        file_id = str(uuid.uuid4())
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        print(f"✅ File saved: {file_path}")

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
        cursor.execute(
            'INSERT INTO user_documents (user_id, file_id, filename, chunk_count) VALUES (?, ?, ?, ?)',
            (user['id'], file_id, filename, len(chunks))
        )
        conn.commit()
        conn.close()

        print(f"✅ Done — {len(chunks)} chunks")
        return _cors_response({
            'message': 'File uploaded and processed successfully',
            'file_id': file_id,
            'filename': filename,
            'chunks': len(chunks),
            'status': 'processed'
        })
    except Exception as e:
        print(f"❌ Upload error: {e}")
        import traceback; traceback.print_exc()
        return _cors_response({'error': str(e)}, 500)


@app.route('/api/status/<file_id>', methods=['GET', 'OPTIONS'])
@login_required
def handle_status(file_id):
    if request.method == 'OPTIONS':
        return _cors_preflight()

    user = get_current_user()
    if user['id'] in app.user_uploads and file_id in app.user_uploads[user['id']]:
        info = app.user_uploads[user['id']][file_id]
        return _cors_response({
            'status': info.get('status', 'unknown'),
            'file_id': file_id,
            'filename': info['filename'],
            'chunks': info.get('chunks', 0)
        })
    return _cors_response({'error': 'File not found'}, 404)

# ============================================
# CHAT ENDPOINT
# ============================================

@app.route('/api/chat', methods=['POST', 'OPTIONS'])
@login_required
def handle_chat():
    if request.method == 'OPTIONS':
        return _cors_preflight()

    user = get_current_user()

    if user['id'] not in app.user_uploads or not app.user_uploads[user['id']]:
        print(f"📂 Loading documents for user {user['id']} from DB")
        load_user_documents_to_memory(user['id'])

    try:
        data = request.json
        if not data or 'message' not in data:
            return _cors_response({'error': 'No message provided'}, 400)

        message = data['message']
        file_id = data.get('file_id')

        if not file_id:
            return _cors_response({'error': 'No file selected'}, 400)

        if user['id'] not in app.user_uploads or file_id not in app.user_uploads[user['id']]:
            return _cors_response({'error': 'File not found. Please upload again.'}, 404)

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
                return _cors_response({'error': 'Document not properly processed'}, 404)

        embedding_service = get_embedding_service()
        question_embedding = embedding_service.generate_embedding(message)
        relevant_chunks = vector_store.similarity_search(question_embedding, k=5)

        if not relevant_chunks:
            return _cors_response({
                'answer': "I couldn't find relevant information in the document to answer your question.",
                'sources': []
            })

        groq_service = get_groq_service()
        result = groq_service.generate_answer(message, relevant_chunks, data.get('history', []))

        return _cors_response({
            'answer': result['answer'],
            'sources': result['sources'],
            'file_id': file_id
        })

    except Exception as e:
        print(f"❌ Chat error: {e}")
        import traceback; traceback.print_exc()
        return _cors_response({'error': str(e)}, 500)

# ============================================
# HEALTH ENDPOINTS
# ============================================

@app.route('/healthz')
def healthz():
    """
    Bare-minimum health check for Render.
    DO NOT call Groq or any external service here —
    a slow/failed API call will make Render think the app is down
    and trigger a restart loop.
    """
    return jsonify({'status': 'ok'}), 200


@app.route('/api/health', methods=['GET', 'OPTIONS'])
def handle_health():
    if request.method == 'OPTIONS':
        return _cors_preflight()

    groq_ok = False
    try:
        groq_service = get_groq_service()
        groq_ok = groq_service.test_connection()
    except Exception:
        pass

    return _cors_response({
        'status': 'healthy',
        'groq_connected': groq_ok,
        'database': os.path.exists(DATABASE_PATH),
        'session': bool(session.get('user_id'))
    })

# ============================================
# DEBUG ROUTES
# ============================================

@app.route('/api/debug/user-files', methods=['GET'])
@login_required
def debug_user_files():
    user = get_current_user()
    if user['id'] not in app.user_uploads or not app.user_uploads[user['id']]:
        load_user_documents_to_memory(user['id'])

    memory_files = [
        {'file_id': fid, 'filename': info.get('filename'), 'status': info.get('status'), 'chunks': info.get('chunks')}
        for fid, info in app.user_uploads.get(user['id'], {}).items()
    ]

    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT file_id, filename, chunk_count FROM user_documents WHERE user_id = ?', (user['id'],))
    db_files = [{'file_id': r[0], 'filename': r[1], 'chunks': r[2]} for r in cursor.fetchall()]
    conn.close()

    return _cors_response({'user': user, 'memory_files': memory_files, 'database_files': db_files})

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
    port = int(os.environ.get('PORT', 5000))
    print(f"\n🌐 SERVER AT http://localhost:{port}\n")
    if IS_RENDER:
        app.run(debug=False, port=port, host='0.0.0.0', use_reloader=False)
    else:
        app.run(debug=True, port=port, host='0.0.0.0')