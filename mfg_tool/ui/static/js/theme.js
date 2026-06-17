// Copyright 2026 Espressif Systems (Shanghai) PTE LTD
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

const STORAGE_KEY = 'esp-matter-tools-theme';
const toggle = document.getElementById('themeToggle');
const root = document.documentElement;

function applyTheme(theme) {
  root.setAttribute('data-theme', theme);
  localStorage.setItem(STORAGE_KEY, theme);
  toggle.textContent = theme === 'dark' ? '☀️' : '🌙';
  toggle.title = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
}

const current = root.getAttribute('data-theme') || 'light';
toggle.textContent = current === 'dark' ? '☀️' : '🌙';
toggle.title = current === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';

toggle.addEventListener('click', () => {
  applyTheme(root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
});
