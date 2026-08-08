# GEMINI.md - Python & Web Development Context

## 🐍 Python Environment & Tooling
* **Interpreter:** Assume Python 3.10 or higher. Use `match/case` syntax where appropriate.
* **Package Manager:**
    * **Priority 1:** `uv` (Ultra-fast, modern).
    * **Priority 2:** `poetry` (Standard for dependency management).
    * **Priority 3:** `pip` (Legacy - use only if no `pyproject.toml` exists).
* **Linting:** Adhere to `Ruff` (preferred) or `Flake8` standards.
* **Formatting:** Strict `Black` formatting. Double quotes for strings, trailing commas in lists.

## 📝 Python Code Style & Quality
### 1. Type Hinting (Mandatory)
All function signatures must be typed. Use modern syntax (`list[str]`, `dict[str, Any]`, `str | None`).
```python
# CORRECT
def calculate_total(items: list[float]) -> float:
    ...
```

### 2. Documentation
* **Docstrings:** Google Style. Every public module, class, and method needs a docstring.
* **Inline Comments:** Use sparingly. Code should be self-documenting. Comment "Why", not "How".

### 3. Modern Idioms
* Use `pathlib.Path` over `os.path`.
* Use `f-strings` over `.format()` or `%` formatting.
* Use `dataclasses` or `Pydantic` models instead of passing around raw dictionaries.
* Use Context Managers (`with open(...)`) for all I/O operations.

## 🧪 Python Testing Standards
* **Framework:** `pytest` is the default.
* **Practices:**
    * Use `conftest.py` for shared fixtures.
    * Use `unittest.mock` to mock external APIs.
    * Do not use `print()` in tests; use `assert` logic.

## 📊 Data Science Specifics
* **Pandas:** Use method chaining where readable. Avoid iterating over rows (`iterrows`)—use vectorization.
* **Notebooks:** If working with `.ipynb`, suggest extracting complex logic into `.py` modules for version control.

---

## 🌐 Modern Web Development (Frontend & Full Stack)
**Focus:** React, Next.js, Vue, Svelte, TypeScript.

### 1. Tech Stack Awareness
* **Language:** TypeScript (Strict Mode) is preferred over JavaScript.
* **Framework Detection:** Look for `next.config.js` (Next.js), `vite.config.ts` (Vite/React/Vue).
* **Styling:** Tailwind CSS is the default preference. Use utility classes.

### 2. Component Architecture
* **Functional Components:** Always use Arrow Functions (`const Card = () => {}`).
* **Colocation:** Keep related files together (`Button.tsx`, `Button.test.tsx`, `Button.module.css`).
* **Props:** Always define a Type or Interface for props. Destructure props in the function signature.
* **Hooks:** Separate complex logic into Custom Hooks (`useUserSession`) to keep the UI layer clean.

### 3. UI & CSS Guidelines
* **Tailwind:** Group classes logically (Layout -> Box Model -> Typography -> Visuals -> Interactive).
* **Responsive:** Mobile-first approach. Write base styles for mobile, then add `md:` or `lg:` overrides.
* **Magic Numbers:** Avoid hardcoded pixel values. Use strict spacing scales (e.g., `w-64`, `rem`).

### 4. Performance & State
* **Rendering:** In Next.js, assume **Server Components** by default. Only use `"use client"` for interactivity.
* **State Management:**
    * Local: `useState`
    * Complex Local: `useReducer`
    * Server: React Query / TanStack Query / SWR. Avoid global stores for server data.



---

## 🏋️ Arbox Membership ID Renewal Workflow (SOP)
Whenever an annual or monthly membership renews, `ARBOX_MEMBERSHIP_USER_ID` expires and returns HTTP status `518`.

### Exact 30-Second Retrieval Procedure (DO NOT USE PROXIES OR ENUMERATION)
1. Direct the user to open:
   `https://site.arboxapp.com/schedule?identifier=f1UhUDad1588686203`
2. Open **F12** (Developer Tools) -> **Network** tab -> filter by **`insert`**.
3. Sign in, click **Book** on any session.
4. Copy `"membership_user_id"` from the `insert` request payload.
5. Update `ARBOX_MEMBERSHIP_USER_ID` in `.env` and GitHub Repository Secrets.

