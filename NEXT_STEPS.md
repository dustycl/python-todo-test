# Next Steps

Ideas for future development of the todo app.

## Completed

- **Categories/tags** — users can organize todos with tags and filter by them
- **Search and filter** — search todos by title, filter by status
- **Due dates** — optional due date per todo
- **Migration system** — forward-only numbered SQL migrations
- **Logging** — request tracking, auth events, and CRUD operations
- **UI cleanup** — progressive disclosure and dedicated stylesheet
- **Todo descriptions** — optional body text beyond just the title
- **Undo delete** — soft deletes with floating toast notifications and progress bar
- **Linting/formatting** — ruff for linting (E/F/W/I rules) and formatting
- **Docker setup** — Dockerfile and docker-compose.yml for containerized deployment
- **Production WSGI server** — gunicorn as the container entrypoint

## Feature Additions

- **Priority levels** — high/medium/low with visual indicators and sorting
- **Bulk operations** — "delete all completed", "mark all as done"
- **Dark mode toggle** — the template already has `data-theme="light"`, just needs a switcher
- **Import/export** — CSV or JSON export of todos

## UX Improvements

- **Pagination** — currently loads all todos at once
- **Drag-and-drop reordering** — custom sort order
- **Inline editing** — edit titles without navigating to a separate page

## Production Readiness

- **CI/CD pipeline** — GitHub Actions for tests + linting

## API Layer

- **REST API** — JSON endpoints alongside the HTML views, enabling a future SPA or mobile client
