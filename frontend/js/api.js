const API_BASE_URL = 'http://localhost:5000/api';

async function apiCall(endpoint, method = 'GET', data = null) {
    const options = {
        method,
        headers: {},
        credentials: 'include'  // Important: Include cookies for authentication
    };

    if (data) {
        if (data instanceof FormData) {
            options.body = data;
            // Don't set Content-Type for FormData - browser sets it with boundary
        } else {
            options.headers['Content-Type'] = 'application/json';
            options.body = JSON.stringify(data);
        }
    }

    console.log(`API Call: ${method} ${endpoint}`, options);

    try {
        const response = await fetch(`${API_BASE_URL}${endpoint}`, options);
        console.log('Response status:', response.status);
        
        // Handle unauthorized
        if (response.status === 401) {
            console.log('Unauthorized - redirecting to login');
            window.location.href = '/login';
            throw new Error('Please login to continue');
        }
        
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