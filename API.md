# API Reference

All routes return server-rendered HTML. Destructive actions use POST to prevent CSRF via links.

## Authentication

| Route | Method | Auth | Description |
|-------|--------|------|-------------|
| `/auth/register` | GET | No | Show registration form |
| `/auth/register` | POST | No | Create a new account. Fields: `username`, `password`, `confirm`, `csrf_token` |
| `/auth/login` | GET | No | Show login form |
| `/auth/login` | POST | No | Log in. Fields: `username`, `password`, `csrf_token`. Supports `?next=` redirect |
| `/auth/logout` | POST | Yes | Log out. Fields: `csrf_token` |

### Registration Validation

- Username: 3-30 alphanumeric characters, must be unique
- Password: at least 8 characters
- Confirm: must match password

### Login Behavior

- On success: redirects to `/` (or `?next=` URL if present)
- On failure: flashes "Invalid username or password"
- Logged-in users visiting `/auth/login` or `/auth/register` are redirected to `/`

## Todos

All todo routes require authentication. Unauthenticated requests are redirected to `/auth/login`.

| Route | Method | Description |
|-------|--------|-------------|
| `/` | GET | List current user's todos (incomplete first, then completed) |
| `/add` | POST | Add a new todo. Fields: `title`, `csrf_token` |
| `/toggle/<id>` | POST | Toggle a todo's completed status. Fields: `csrf_token` |
| `/edit/<id>` | GET | Show edit form for a todo |
| `/edit/<id>` | POST | Update a todo's title. Fields: `title`, `csrf_token` |
| `/delete/<id>` | POST | Delete a todo. Fields: `csrf_token` |

### Todo Validation

- Title: required, max 200 characters, whitespace-trimmed

### Ownership

Every todo operation is scoped to the current user. Attempting to access another user's todo returns 404.

## CSRF Protection

All POST requests must include a valid `csrf_token` field. The token is:

1. Generated per session and stored server-side
2. Injected into templates via a context processor
3. Validated by a `before_request` hook

Requests with a missing or invalid token receive a `400 Bad Request` response.

## Error Responses

| Status | Meaning |
|--------|---------|
| 400 | CSRF token missing or invalid |
| 404 | Page/resource not found, or todo belongs to another user |
| 500 | Unexpected server error |
