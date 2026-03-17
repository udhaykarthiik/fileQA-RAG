document.addEventListener('DOMContentLoaded', function() {
    console.log('Chat.js loaded');
    initializeChat();
});

let currentFileId = null;
let messageHistory = [];

function initializeChat() {
    // Get file info from session storage
    currentFileId = sessionStorage.getItem('currentFileId');
    const filename = sessionStorage.getItem('currentFilename');
    
    console.log('Initializing chat with:', { currentFileId, filename });
    
    const messagesDiv = document.getElementById('messages');
    const userInput = document.getElementById('userInput');
    const sendButton = document.getElementById('sendButton');
    const currentFileDiv = document.getElementById('currentFile');
    
    if (currentFileId && filename) {
        // Update UI with file info
        currentFileDiv.innerHTML = `<span class="file-name">📄 ${filename}</span>`;
        userInput.disabled = false;
        sendButton.disabled = false;
        userInput.focus();
        
        // Add welcome message
        addMessage(`✅ Document "${filename}" loaded successfully! Ask me anything about it.`, false);
    } else {
        currentFileDiv.innerHTML = '<span class="file-name">⚠️ No file selected</span>';
        addMessage('Please upload a document first to start chatting.', false);
    }
    
    // Setup form submission
    const chatForm = document.getElementById('chatForm');
    chatForm.addEventListener('submit', handleSubmit);
}

async function handleSubmit(e) {
    e.preventDefault();
    
    const userInput = document.getElementById('userInput');
    const message = userInput.value.trim();
    
    if (!message || !currentFileId) {
        console.log('Cannot send: message or fileId missing', { message, currentFileId });
        return;
    }
    
    console.log('Sending message:', message);
    
    // Clear input
    userInput.value = '';
    
    // Add user message to chat
    addMessage(message, true);
    
    // Show typing indicator
    showTypingIndicator(true);
    
    try {
        // Send to backend
        const response = await apiCall('/chat', 'POST', {
            message: message,
            file_id: currentFileId,
            history: messageHistory.slice(-6)
        });
        
        console.log('Got response:', response);
        
        // Hide typing indicator
        showTypingIndicator(false);
        
        // Add bot response
        addMessage(response.answer, false, response.sources);
        
        // Update history
        messageHistory.push(
            { role: 'user', content: message },
            { role: 'assistant', content: response.answer }
        );
        
        // Keep only last 10 messages
        if (messageHistory.length > 10) {
            messageHistory = messageHistory.slice(-10);
        }
        
    } catch (error) {
        console.error('Chat error:', error);
        showTypingIndicator(false);
        addMessage(`❌ Error: ${error.message}. Please try again.`, false);
    }
}

function addMessage(content, isUser = false, sources = null) {
    const messagesDiv = document.getElementById('messages');
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${isUser ? 'user' : ''}`;
    
    let messageHTML = `<div class="message-content">${content}</div>`;
    
    // Add sources if available
    if (sources && sources.length > 0) {
        messageHTML += '<div class="sources"><small>📚 Sources:</small>';
        sources.forEach(source => {
            messageHTML += `<div class="source-item" title="${source.text || ''}">📄 Similarity: ${Math.round((source.score || 0) * 100)}%</div>`;
        });
        messageHTML += '</div>';
    }
    
    messageDiv.innerHTML = messageHTML;
    messagesDiv.appendChild(messageDiv);
    
    // Scroll to bottom
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function showTypingIndicator(show) {
    const indicator = document.getElementById('typingIndicator');
    if (indicator) {
        indicator.style.display = show ? 'flex' : 'none';
    }
}

// API call function with better error handling
async function apiCall(endpoint, method = 'GET', data = null) {
    const API_BASE_URL = 'http://localhost:5000/api';
    
    const options = {
        method,
        headers: {
            'Content-Type': 'application/json'
        },
        credentials: 'same-origin'
    };

    if (data) {
        options.body = JSON.stringify(data);
    }

    console.log(`🌐 API Call: ${method} ${endpoint}`, data);

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