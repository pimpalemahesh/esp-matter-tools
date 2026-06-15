const STORAGE_KEY = 'esp-matter-tools-theme';
const toggle = document.getElementById('themeToggle');
const root = document.documentElement;

function applyTheme(theme) {
  root.setAttribute('data-theme', theme);
  localStorage.setItem(STORAGE_KEY, theme);
  toggle.textContent = theme === 'dark' ? '☀️' : '🌙';
  toggle.title = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
}

// Sync button icon with the theme already set by the inline <head> script (no FOUC re-apply)
const current = root.getAttribute('data-theme') || 'light';
toggle.textContent = current === 'dark' ? '☀️' : '🌙';
toggle.title = current === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';

toggle.addEventListener('click', () => {
  applyTheme(root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
});
