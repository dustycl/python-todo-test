# Next Steps

Ideas for future development of the todo app.

## Completed

- **Categories/tags** — users can organize todos with tags and filter by them
- **Search and filter** — search todos by title, filter by status
- **Due dates** — optional due date per todo
- **Migration system** — forward-only numbered SQL migrations
- **Logging** — request tracking, auth events, and CRUD operations
- **UI cleanup** — progressive disclosure and dedicated stylesheet

## Feature Additions

- **Priority levels** — high/medium/low with visual indicators and sorting
- **Todo descriptions** — optional body text beyond just the title
- **Bulk operations** — "delete all completed", "mark all as done"
- **Dark mode toggle** — the template already has `data-theme="light"`, just needs a switcher
- **Import/export** — CSV or JSON export of todos

## UX Improvements

- **Pagination** — currently loads all todos at once
- **Drag-and-drop reordering** — custom sort order
- **Undo delete** — soft deletes with a trash/restore flow
- **Inline editing** — edit titles without navigating to a separate page

## Production Readiness

- **Docker setup** — containerize for deployment
- **CI/CD pipeline** — GitHub Actions for tests + linting
- **Production WSGI server** — gunicorn config
- **Linting/formatting** — black, flake8, or ruff

## API Layer

- **REST API** — JSON endpoints alongside the HTML views, enabling a future SPA or mobile client
