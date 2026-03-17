from flask import Blueprint, request, jsonify, current_app
import os
from werkzeug.utils import secure_filename
import uuid

upload_bp = Blueprint('upload', __name__)

ALLOWED_EXTENSIONS = {'txt', 'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@upload_bp.route('/upload', methods=['POST'])
def upload_file():
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
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        print(f"✅ File saved: {file_path}")
        
        # Store file info in app config (in memory - for demo)
        if not hasattr(current_app, 'uploaded_files'):
            current_app.uploaded_files = {}
        
        current_app.uploaded_files[file_id] = {
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
        print(f"❌ Error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@upload_bp.route('/status/<file_id>', methods=['GET'])
def get_status(file_id):
    if hasattr(current_app, 'uploaded_files') and file_id in current_app.uploaded_files:
        return jsonify({
            'status': 'processed',
            'file_id': file_id,
            'filename': current_app.uploaded_files[file_id]['filename']
        }), 200
    return jsonify({'error': 'File not found'}), 404