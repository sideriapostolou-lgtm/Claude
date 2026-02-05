# CLAUDE.md - AI Assistant Guidelines

This file provides guidance for AI assistants (like Claude) working with this repository.

## Project Overview

This is the Claude repository. It serves as a foundation for AI-assisted development workflows.

## Repository Structure

```
Claude/
├── CLAUDE.md          # AI assistant guidelines (this file)
├── src/               # Source code (to be created)
├── tests/             # Test files (to be created)
├── docs/              # Documentation (to be created)
└── .git/              # Git version control
```

## Development Setup

### Prerequisites

- Git installed and configured
- Appropriate language runtime (TBD based on project type)

### Getting Started

```bash
# Clone the repository
git clone <repository-url>
cd Claude

# Install dependencies (when applicable)
# npm install  # for Node.js projects
# pip install -r requirements.txt  # for Python projects
```

## Development Workflow

### Branch Naming Convention

- Feature branches: `feature/<description>`
- Bug fixes: `fix/<description>`
- Documentation: `docs/<description>`
- AI-assisted development: `claude/<description>-<session-id>`

### Commit Messages

Follow conventional commit format:
- `feat:` - New features
- `fix:` - Bug fixes
- `docs:` - Documentation changes
- `refactor:` - Code refactoring
- `test:` - Test additions or modifications
- `chore:` - Maintenance tasks

Example: `feat: add user authentication module`

### Pull Request Guidelines

1. Create a feature branch from main
2. Make changes with clear, atomic commits
3. Ensure all tests pass
4. Update documentation as needed
5. Create PR with descriptive title and body

## Code Style and Conventions

### General Principles

- Write clean, readable code
- Follow the DRY (Don't Repeat Yourself) principle
- Keep functions small and focused
- Use meaningful variable and function names
- Add comments only when the code isn't self-explanatory

### File Organization

- Group related functionality together
- Keep files focused on a single responsibility
- Use consistent naming conventions across the project

## Testing

### Running Tests

```bash
# Run all tests (command will depend on project type)
# npm test
# pytest
# go test ./...
```

### Writing Tests

- Write tests for new features
- Maintain test coverage for critical paths
- Use descriptive test names that explain what is being tested

## AI Assistant Guidelines

### When Working with This Repository

1. **Read before editing**: Always read relevant files before making changes
2. **Understand context**: Review related code to understand patterns and conventions
3. **Minimal changes**: Make only the changes necessary to accomplish the task
4. **Preserve style**: Match existing code style and conventions
5. **Test changes**: Run tests after making modifications

### Security Considerations

- Never commit secrets, API keys, or credentials
- Validate user input at system boundaries
- Follow OWASP security guidelines
- Review changes for potential vulnerabilities

### Communication

- Provide clear explanations of changes made
- Ask for clarification when requirements are ambiguous
- Report any issues or blockers encountered
- Document significant architectural decisions

## Configuration Files

(To be updated as the project develops)

| File | Purpose |
|------|---------|
| `.gitignore` | Git ignore patterns |
| `CLAUDE.md` | AI assistant guidelines |

## Useful Commands

```bash
# Git operations
git status                    # Check current state
git diff                      # View changes
git log --oneline -10         # Recent commits

# Development (examples - update based on project type)
# npm run dev                 # Start development server
# npm run build               # Build for production
# npm run lint                # Run linter
```

## Contact and Resources

- Repository: [GitHub Link]
- Documentation: [Docs Link]
- Issue Tracker: [Issues Link]

---

*This file should be updated as the project evolves to reflect current practices and conventions.*
