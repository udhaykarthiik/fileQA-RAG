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
    if (browseBtn) {
        browseBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            console.log('Browse button clicked');
            fileInput.click();
        });
    }

    // File selection
    fileInput.addEventListener('change', function(e) {
        console.log('File input changed', e.target.files);
        handleFileSelect(e);
    });

    // Drag and drop
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.style.borderColor = '#764ba2';
        uploadArea.style.background = 'rgba(255,255,255,0.1)';
    });

    uploadArea.addEventListener('dragleave', (e) => {
        e.preventDefault();
        uploadArea.style.borderColor = 'rgba(255,255,255,0.3)';
        uploadArea.style.background = 'rgba(255,255,255,0.05)';
    });

    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        console.log('File dropped');
        uploadArea.style.borderColor = 'rgba(255,255,255,0.3)';
        uploadArea.style.background = 'rgba(255,255,255,0.05)';
        
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
    
    const uploadArea = document.getElementById('uploadArea');
    const uploadStatus = document.getElementById('uploadStatus');
    const uploadProgress = document.querySelector('.upload-progress');
    
    // Show loading state
    uploadArea.style.display = 'none';
    uploadStatus.style.display = 'block';
    uploadStatus.className = 'upload-status info';
    uploadStatus.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Uploading and processing your document...';
    
    if (uploadProgress) {
        uploadProgress.style.display = 'block';
    }
    
    const formData = new FormData();
    formData.append('file', file);

    try {
        console.log('Sending upload request...');
        
        // Make sure to include credentials for session cookie
        const response = await fetch('/api/upload', {
            method: 'POST',
            body: formData,
            credentials: 'include'  // Important: Include cookies for authentication
        });
        
        console.log('Response status:', response.status);
        
        if (response.status === 401) {
            // Not authenticated - redirect to login
            updateUploadStatus('error', 'Please login to upload documents. Redirecting...');
            setTimeout(() => {
                window.location.href = '/login';
            }, 2000);
            return;
        }
        
        const result = await response.json();
        console.log('Upload result:', result);
        
        if (!response.ok) {
            throw new Error(result.error || `Upload failed with status ${response.status}`);
        }
        
        // Success
        updateUploadStatus('success', `✅ File uploaded successfully! ${result.chunks} chunks created. Redirecting to chat...`);
        
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
        updateUploadStatus('error', `❌ Upload failed: ${error.message}`);
        
        // Show upload area again after error
        setTimeout(() => {
            uploadArea.style.display = 'block';
            uploadStatus.style.display = 'none';
            if (uploadProgress) {
                uploadProgress.style.display = 'none';
            }
        }, 3000);
    }
}

function updateUploadStatus(type, message) {
    const uploadStatus = document.getElementById('uploadStatus');
    uploadStatus.className = `upload-status ${type}`;
    uploadStatus.innerHTML = `<i class="fas ${type === 'success' ? 'fa-check-circle' : type === 'error' ? 'fa-exclamation-circle' : 'fa-info-circle'}"></i> ${message}`;
}