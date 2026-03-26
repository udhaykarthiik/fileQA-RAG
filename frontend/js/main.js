// main.js — only runs on /home page
// DO NOT add redirects here — they cause reload loops on other pages

document.addEventListener('DOMContentLoaded', function() {
    console.log('main.js loaded on:', window.location.pathname);

    // Only run auth UI update on home page
    // dashboard.html, chat.html, login.html, signup.html handle their own auth
    if (window.location.pathname === '/home' || window.location.pathname === '/') {
        checkAuthStatus();
    }
});

async function checkAuthStatus() {
    try {
        const response = await fetch('/api/auth/me', { credentials: 'include' });

        if (response.ok) {
            const data = await response.json();
            if (data.user) {
                showLoggedInNav(data.user);
            } else {
                showLoggedOutNav();
            }
        } else {
            // 401 on home page = just show logged-out UI, never redirect
            showLoggedOutNav();
        }
    } catch (error) {
        // Network error — show logged-out UI, never redirect
        console.error('Auth check error:', error);
        showLoggedOutNav();
    }
}

function showLoggedInNav(user) {
    const authButtons = document.getElementById('authButtons');
    const userMenu    = document.getElementById('userMenu');
    const userName    = document.getElementById('userName');
    const dashLink    = document.getElementById('dashboardLink');

    if (authButtons) authButtons.style.display = 'none';
    if (userMenu)    userMenu.style.display = 'flex';
    if (userName)    userName.textContent = user.username || user.full_name || 'User';
    if (dashLink)    dashLink.style.display = 'inline-flex';
}

function showLoggedOutNav() {
    const authButtons = document.getElementById('authButtons');
    const userMenu    = document.getElementById('userMenu');
    const dashLink    = document.getElementById('dashboardLink');

    if (authButtons) authButtons.style.display = 'flex';
    if (userMenu)    userMenu.style.display = 'none';
    if (dashLink)    dashLink.style.display = 'none';
}