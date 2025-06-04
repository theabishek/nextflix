export const TMDB_API_KEY = '1a483b7f5ffd41254a97bd00fa4ee773';
export const TMDB_BASE_URL = 'https://api.themoviedb.org/3';

// Toggle password visibility
function setupPasswordToggle() {
    const togglePassword = document.querySelector('.toggle-password');
    if (!togglePassword) return;
  
    const passwordInput = document.getElementById('password');
    
    togglePassword.addEventListener('click', function() {
      const type = passwordInput.getAttribute('type') === 'password' ? 'text' : 'password';
      passwordInput.setAttribute('type', type);
      this.classList.toggle('fa-eye');
      this.classList.toggle('fa-eye-slash');
    });
  }
  
  document.addEventListener('DOMContentLoaded', () => {
    setupPasswordToggle();
    setupCountryDatalist();
  });