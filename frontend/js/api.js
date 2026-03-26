// Use relative URLs — works on both localhost and Render
const API_BASE_URL = '/api';

async function apiCall(endpoint, method = 'GET', data = null) {
    const options = {
        method,
        headers: {},
        credentials: 'include'
    };

    if (data) {
        if (data instanceof FormData) {
            options.body = data;
        } else {
            options.headers['Content-Type'] = 'application/json';
            options.body = JSON.stringify(data);
        }
    }

    console.log(`API Call: ${method} ${endpoint}`);

    try {
        const response = await fetch(`${API_BASE_URL}${endpoint}`, options);
        console.log('Response status:', response.status);

        if (response.status === 401) {
            console.log('Unauthorized - redirecting to login');
            window.location.href = '/login';
            throw new Error('Please login to continue');
        }

        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.error || `HTTP error ${response.status}`);
        }

        return result;
    } catch (error) {
        console.error('API Error:', error);
        throw error;
    }
}