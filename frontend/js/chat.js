document.addEventListener('DOMContentLoaded', function() {
    console.log('Chat.js loaded');
    initializeChat();
    checkAuthStatus();
});

let currentFileId = null;
let messageHistory = [];
let currentUser = null;

// Check authentication status
async function checkAuthStatus() {
    try {
        const response = await fetch('/api/auth/me', {
            method: 'GET',
            credentials: 'include',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        if (response.ok) {
            const data = await response.json();
            currentUser = data.user;
            console.log('User authenticated:', currentUser);
        } else {
            console.log('User not authenticated, redirecting to login...');
            showNotification('Please login to continue', 'error');
            setTimeout(() => {
                window.location.href = '/login';
            }, 1500);
        }
    } catch (error) {
        console.error('Auth check error:', error);
    }
}

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
        if (currentFileDiv) {
            currentFileDiv.innerHTML = `
                <div class="file-icon">
                    <i class="fas fa-file-pdf"></i>
                </div>
                <div class="file-details">
                    <span class="file-name">📄 ${filename}</span>
                    <span class="file-status">Ready for chat</span>
                </div>
            `;
        }
        userInput.disabled = false;
        sendButton.disabled = false;
        userInput.focus();
        
        // Add welcome message
        addMessage(`✅ Document "${filename}" loaded successfully! Ask me anything about it.`, false);
    } else {
        if (currentFileDiv) {
            currentFileDiv.innerHTML = `
                <div class="file-icon">
                    <i class="fas fa-exclamation-triangle"></i>
                </div>
                <div class="file-details">
                    <span class="file-name">⚠️ No file selected</span>
                    <span class="file-status">Please upload a document first</span>
                </div>
            `;
        }
        addMessage('Please upload a document first to start chatting.', false);
    }
    
    // Setup form submission
    const chatForm = document.getElementById('chatForm');
    if (chatForm) {
        chatForm.addEventListener('submit', handleSubmit);
    }
}

async function handleSubmit(e) {
    e.preventDefault();
    
    const userInput = document.getElementById('userInput');
    const message = userInput.value.trim();
    
    if (!message) {
        console.log('Cannot send: empty message');
        return;
    }
    
    if (!currentFileId) {
        showNotification('No document selected. Please upload a document first.', 'error');
        setTimeout(() => {
            window.location.href = '/home';
        }, 1500);
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
        // Send to backend with credentials
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            credentials: 'include',  // Important: Include cookies for authentication
            body: JSON.stringify({
                message: message,
                file_id: currentFileId,
                history: messageHistory.slice(-6)
            })
        });
        
        console.log('Response status:', response.status);
        
        // Handle unauthorized
        if (response.status === 401) {
            showNotification('Session expired. Please login again.', 'error');
            setTimeout(() => {
                window.location.href = '/login';
            }, 1500);
            return;
        }
        
        const data = await response.json();
        console.log('Got response:', data);
        
        if (!response.ok) {
            throw new Error(data.error || `HTTP error ${response.status}`);
        }
        
        // Hide typing indicator
        showTypingIndicator(false);
        
        // Add bot response
        addMessage(data.answer, false, data.sources);
        
        // Update history
        messageHistory.push(
            { role: 'user', content: message },
            { role: 'assistant', content: data.answer }
        );
        
        // Keep only last 10 messages
        if (messageHistory.length > 10) {
            messageHistory = messageHistory.slice(-10);
        }
        
        // Update token count if element exists
        const tokenCount = document.getElementById('tokenCount');
        if (tokenCount) {
            const totalTokens = messageHistory.reduce((sum, msg) => sum + msg.content.length, 0);
            tokenCount.textContent = `${Math.floor(totalTokens / 4)} tokens`;
        }
        
    } catch (error) {
        console.error('Chat error:', error);
        showTypingIndicator(false);
        
        let errorMessage = 'An error occurred. Please try again.';
        if (error.message.includes('401') || error.message.includes('Authentication')) {
            errorMessage = 'Your session has expired. Please login again.';
            setTimeout(() => {
                window.location.href = '/login';
            }, 2000);
        } else if (error.message.includes('404')) {
            errorMessage = 'Document not found. Please upload again.';
            setTimeout(() => {
                window.location.href = '/home';
            }, 2000);
        }
        
        addMessage(`❌ Error: ${errorMessage}`, false);
    }
}

function addMessage(content, isUser = false, sources = null) {
    const messagesDiv = document.getElementById('messages');
    if (!messagesDiv) return;
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${isUser ? 'user' : 'bot'}`;
    
    const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    
    let messageHTML = `
        <div class="message-avatar">
            <i class="fas ${isUser ? 'fa-user' : 'fa-robot'}"></i>
        </div>
        <div class="message-content-wrapper">
            <div class="message-header">
                <span class="message-sender">${isUser ? 'You' : 'FileQA Assistant'}</span>
                <span class="message-time">${timestamp}</span>
            </div>
            <div class="message-content">${escapeHtml(content)}</div>
    `;
    
    // Add sources if available (only for bot messages)
    if (sources && sources.length > 0 && !isUser) {
        messageHTML += `
            <div class="sources">
                <small>📚 Sources:</small>
                ${sources.map(source => `
                    <div class="source-item" title="${escapeHtml(source.text || '')}">
                        📄 Similarity: ${Math.round((source.score || 0) * 100)}%
                    </div>
                `).join('')}
            </div>
            <div class="message-actions">
                <button class="message-action" onclick="copyMessage(this)">
                    <i class="far fa-copy"></i>
                </button>
                <button class="message-action" onclick="speakMessage(this)">
                    <i class="fas fa-volume-up"></i>
                </button>
            </div>
        </div>
        `;
    } else {
        messageHTML += `</div>`;
    }
    
    messageDiv.innerHTML = messageHTML;
    messagesDiv.appendChild(messageDiv);
    
    // Scroll to bottom
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

// Helper function to escape HTML
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Copy message to clipboard
function copyMessage(button) {
    const messageContent = button.closest('.message-content-wrapper').querySelector('.message-content');
    const text = messageContent.innerText;
    
    navigator.clipboard.writeText(text).then(() => {
        const originalHtml = button.innerHTML;
        button.innerHTML = '<i class="fas fa-check"></i>';
        setTimeout(() => {
            button.innerHTML = originalHtml;
        }, 2000);
        showNotification('Copied to clipboard!', 'success');
    }).catch(() => {
        showNotification('Failed to copy', 'error');
    });
}

// Text-to-speech
function speakMessage(button) {
    const messageContent = button.closest('.message-content-wrapper').querySelector('.message-content');
    const text = messageContent.innerText;
    
    if ('speechSynthesis' in window) {
        // Stop any ongoing speech
        window.speechSynthesis.cancel();
        
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = 0.9;
        utterance.pitch = 1;
        utterance.lang = 'en-US';
        
        // Get a female voice if available
        const voices = window.speechSynthesis.getVoices();
        const femaleVoice = voices.find(voice => voice.name.includes('Google UK English Female') || voice.name.includes('Samantha'));
        if (femaleVoice) {
            utterance.voice = femaleVoice;
        }
        
        window.speechSynthesis.speak(utterance);
        
        const originalHtml = button.innerHTML;
        button.innerHTML = '<i class="fas fa-stop"></i>';
        
        utterance.onend = () => {
            button.innerHTML = originalHtml;
        };
    } else {
        showNotification('Text-to-speech not supported in your browser', 'error');
    }
}

function showTypingIndicator(show) {
    const indicator = document.getElementById('typingIndicator');
    if (indicator) {
        indicator.style.display = show ? 'flex' : 'none';
    }
}

function showNotification(message, type) {
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.innerHTML = `
        <i class="fas ${type === 'success' ? 'fa-check-circle' : 'fa-exclamation-circle'}"></i>
        <span>${message}</span>
    `;
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.remove();
    }, 3000);
}

// Clear chat function
function clearChat() {
    const messagesDiv = document.getElementById('messages');
    if (messagesDiv && confirm('Are you sure you want to clear the chat?')) {
        messagesDiv.innerHTML = '';
        messageHistory = [];
        
        // Add welcome message back
        const filename = sessionStorage.getItem('currentFilename');
        if (filename) {
            addMessage(`✅ Document "${filename}" loaded successfully! Ask me anything about it.`, false);
        } else {
            addMessage('Please upload a document to start chatting.', false);
        }
        
        showNotification('Chat cleared', 'success');
    }
}

// Download chat function
function downloadChat() {
    const messages = document.querySelectorAll('.message');
    let chatText = 'FileQA Chat History\n';
    chatText += '='.repeat(50) + '\n\n';
    
    messages.forEach(msg => {
        const isUser = msg.classList.contains('user');
        const sender = isUser ? 'You' : 'FileQA Assistant';
        const content = msg.querySelector('.message-content')?.innerText || '';
        const time = msg.querySelector('.message-time')?.innerText || '';
        
        chatText += `[${time}] ${sender}:\n${content}\n\n`;
    });
    
    const blob = new Blob([chatText], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `chat-${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.txt`;
    a.click();
    URL.revokeObjectURL(url);
    
    showNotification('Chat downloaded!', 'success');
}

// Make functions globally available
window.copyMessage = copyMessage;
window.speakMessage = speakMessage;
window.clearChat = clearChat;
window.downloadChat = downloadChat;