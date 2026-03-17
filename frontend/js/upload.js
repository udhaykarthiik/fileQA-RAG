document.addEventListener('DOMContentLoaded', function() {
    console.log('Upload.js loaded');
    
    const uploadArea = document.getElementById('uploadArea');
    const fileInput = document.getElementById('fileInput');
    const browseBtn = document.getElementById('browseBtn');
    const uploadStatus = document.getElementById('uploadStatus');

    if (!uploadArea) {
        console.log('Upload area not found - not on upload page');
        return;
    }

    console.log('Upload area found, initializing...');

    // Click on upload area
    uploadArea.addEventListener('click', () => {
        console.log('Upload area clicked');
        fileInput.click();
    });

    // Browse button click
    browseBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        console.log('Browse button clicked');
        fileInput.click();
    });

    // File selection
    fileInput.addEventListener('change', function(e) {
        console.log('File input changed', e.target.files);
        handleFileSelect(e);
    });

    // Drag and drop
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.style.borderColor = '#764ba2';
        uploadArea.style.background = '#f8f9ff';
    });

    uploadArea.addEventListener('dragleave', (e) => {
        e.preventDefault();
        uploadArea.style.borderColor = '#667eea';
        uploadArea.style.background = 'white';
    });

    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        console.log('File dropped');
        uploadArea.style.borderColor = '#667eea';
        uploadArea.style.background = 'white';
        
        const files = e.dataTransfer.files;
        console.log('Dropped files:', files);
        if (files.length > 0) {
            handleFile(files[0]);
        }
    });
});

async function handleFileSelect(e) {
    console.log('handleFileSelect called', e);
    const file = e.target.files[0];
    if (file) {
        console.log('File selected:', file.name, 'Size:', file.size, 'Type:', file.type);
        await handleFile(file);
    }
}

async function handleFile(file) {
    console.log('handleFile called with:', file.name);
    
    // Show loading state
    const uploadArea = document.getElementById('uploadArea');
    const uploadStatus = document.getElementById('uploadStatus');
    
    uploadArea.style.display = 'none';
    uploadStatus.style.display = 'block';
    uploadStatus.className = 'upload-status info';
    uploadStatus.textContent = 'Uploading file...';
    
    const formData = new FormData();
    formData.append('file', file);

    try {
        console.log('Sending upload request...');
        const result = await apiCall('/upload', 'POST', formData);
        console.log('Upload successful:', result);
        
        updateUploadStatus('success', `File uploaded successfully! Redirecting to chat...`);
        
        // Store file_id and filename in session storage
        sessionStorage.setItem('currentFileId', result.file_id);
        sessionStorage.setItem('currentFilename', result.filename);
        
        console.log('Redirecting to chat in 2 seconds...');
        // Redirect to chat page after 2 seconds
        setTimeout(() => {
            window.location.href = '/chat';
        }, 2000);
        
    } catch (error) {
        console.error('Upload failed:', error);
        updateUploadStatus('error', `Upload failed: ${error.message}`);
        
        // Show upload area again after error
        setTimeout(() => {
            uploadArea.style.display = 'block';
            uploadStatus.style.display = 'none';
        }, 3000);
    }
}

function updateUploadStatus(type, message) {
    const uploadStatus = document.getElementById('uploadStatus');
    uploadStatus.className = `upload-status ${type}`;
    uploadStatus.textContent = message;
}

// Override apiCall from api.js with better error handling
async function apiCall(endpoint, method = 'GET', data = null) {
    const API_BASE_URL = 'http://localhost:5000/api';
    
    const options = {
        method,
        headers: {}
    };

    if (data) {
        if (data instanceof FormData) {
            options.body = data;
            // Don't set Content-Type header for FormData, browser sets it with boundary
        } else {
            options.headers['Content-Type'] = 'application/json';
            options.body = JSON.stringify(data);
        }
    }

    console.log(`API Call: ${method} ${endpoint}`, options);

    try {
        const response = await fetch(`${API_BASE_URL}${endpoint}`, options);
        console.log('Response status:', response.status);
        
        const result = await response.json();
        console.log('Response data:', result);
        
        if (!response.ok) {
            throw new Error(result.error || `HTTP error ${response.status}`);
        }
        
        return result;
    } catch (error) {
        console.error('API Error:', error);
        throw error;
    }
}