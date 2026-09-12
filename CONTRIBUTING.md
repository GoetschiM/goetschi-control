# Contributing to Goetschi Control

Thank you for your interest in contributing to Goetschi Control! This document provides guidelines for development, testing, and submitting contributions.

## Development Setup

### Prerequisites
- Git
- Python 3.11+
- Node.js 20+
- pip and npm

### Local Development

1. Clone the repository:
```bash
git clone https://github.com/GoetschiM/goetschi-control.git
cd goetschi-control
```

2. Set up Python environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

3. Set up frontend:
```bash
cd frontend
npm install
cd ..
```

4. Configure environment:
```bash
cp dashboard.env.example dashboard.env
# Edit dashboard.env with your test infrastructure credentials
```

5. Run locally:
```bash
# Terminal 1: Start the Flask backend
python app.py

# Terminal 2 (optional): Build frontend in watch mode
cd frontend
npm run dev
```

The app will be available at `http://localhost:5000` (Flask dev server) or `http://localhost:5173` (Vite dev server for frontend-only changes).

## Code Standards

### Python (Backend)
- Follow PEP 8 style guidelines
- Use type hints where practical
- Add docstrings for public functions/classes
- Test changes locally before submitting

### JavaScript/TypeScript (Frontend)
- Follow the existing code style (see `frontend/src` for patterns)
- Use ES6+ syntax
- Keep components focused and reusable
- Test responsive design on multiple screen sizes

### General
- No hardcoded credentials or secrets
- All sensitive data must use environment variables
- Keep commits focused and descriptive
- Reference relevant issues in commit messages

## Submitting Changes

### Before You Start
1. Open an issue describing the feature or bug (or find an existing one)
2. Discuss the approach in the issue before making major changes
3. Ensure you have permission to contribute your changes

### Making Changes
1. Create a feature branch:
```bash
git checkout -b feature/my-feature-name
```

2. Make your changes and test locally

3. Commit with clear messages:
```bash
git commit -m "Feature: add new monitoring capability

- Describe what was added
- Explain why this change was needed
- Reference issue if applicable: closes #123"
```

4. Push to your fork and create a pull request

### Pull Request Guidelines
- Include a clear description of the changes
- Reference any related issues
- Include before/after screenshots for UI changes
- Ensure all tests pass (if applicable)
- Keep the scope focused — split large changes into multiple PRs

## Testing

### Manual Testing
- Test in both light and dark modes (Settings → Theme)
- Test on mobile devices/responsive views
- Verify integration with your infrastructure services
- Check that sensitive data (logs, configs) is not exposed

### Security Considerations
- Never log or display secrets
- Validate all user inputs
- Escape HTML/JavaScript in dynamic content
- Ensure CORS and CSRF protections are in place

## Reporting Issues

When reporting bugs, include:
- Steps to reproduce
- Expected vs. actual behavior
- Environment details (deployment method, infrastructure, versions)
- Relevant logs (from Settings → Audit Log)
- Screenshots if applicable

**Do NOT include secrets or credentials in issue reports.**

## Architecture Notes

### Key Components
- **app.py**: Flask backend, routing, API endpoints
- **templates/index.html**: SPA entry point
- **frontend/src/**: React components and frontend logic
- **static/**: Built frontend assets and vendor libraries

### Data Flow
1. Frontend sends requests to Flask API endpoints
2. Flask queries infrastructure services (Proxmox API, Prometheus, Loki, etc.)
3. Data is cached in local database (audit.db) where applicable
4. WebSocket (Socket.IO) provides real-time updates

### Adding a New Feature
1. Plan the backend API endpoint in `app.py`
2. Add corresponding frontend component in `frontend/src/`
3. Update environment variables if new services are needed
4. Add integration tests if modifying critical paths
5. Document the feature in ROADMAP.md

## Questions?

- Check the [ROADMAP.md](ROADMAP.md) for planned features and architecture decisions
- Review existing issues and PRs for similar discussions
- Open a discussion if you have questions about the codebase

Thank you for contributing to Goetschi Control!
