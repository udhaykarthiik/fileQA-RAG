// Main initialization
document.addEventListener('DOMContentLoaded', function() {
    console.log('FileQA Chatbot initialized');
    
    // Check authentication status
    checkAuthStatus();
    
    // Check if we're on chat page
    if (window.location.pathname === '/chat') {
        initializeChat();
    }
});

async function checkAuthStatus() {
    try {
        const response = await fetch('/api/auth/me', {
            credentials: 'include'
        });
        
        if (response.ok) {
            const data = await response.json();
            console.log('User authenticated:', data.user);
            
            // Update UI for authenticated user if needed
            const authButtons = document.getElementById('authButtons');
            const userMenu = document.getElementById('userMenu');
            
            if (authButtons && userMenu) {
                authButtons.style.display = 'none';
                userMenu.style.display = 'flex';
                
                const userNameSpan = document.getElementById('userName');
                if (userNameSpan) {
                    userNameSpan.textContent = data.user.username || data.user.full_name;
                }
            }
        } else {
            console.log('User not authenticated');
            
            // Update UI for unauthenticated user
            const authButtons = document.getElementById('authButtons');
            const userMenu = document.getElementById('userMenu');
            
            if (authButtons && userMenu) {
                authButtons.style.display = 'flex';
                userMenu.style.display = 'none';
            }
        }
    } catch (error) {
        console.error('Auth check error:', error);
    }
}

function initializeChat() {
    console.log('Chat interface ready');
    // Chat functionality will be handled by chat.js
}