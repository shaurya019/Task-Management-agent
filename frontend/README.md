# Task Agent Frontend

A React TypeScript frontend for the Task Agent - an AI-powered task management system.

## Features

- **Authentication**: Token-based authentication with demo tokens
- **Task Management**: Create, read, update, and delete tasks
- **Advanced Filtering**: Filter tasks by status, priority, tags, and due date
- **Sorting & Pagination**: Sort by various fields with pagination support
- **AI Agent Chat**: Natural language interface for task management
- **Permission-Aware UI**: Different views based on user roles and scopes
- **Responsive Design**: Mobile-friendly interface
- **Optimistic Locking**: Version conflict handling for concurrent edits

## Prerequisites

- Node.js (v14 or higher)
- npm or yarn
- Task Agent backend running on `http://127.0.0.1:8000`

## Installation

1. Navigate to the frontend directory:
```bash
cd frontend
```

2. Install dependencies:
```bash
npm install
```

3. Create a `.env` file (optional, defaults to localhost:8000):
```bash
REACT_APP_API_BASE_URL=http://127.0.0.1:8000
```

## Running the Application

1. Start the backend server first (see main README)

2. Start the React development server:
```bash
npm start
```

3. Open your browser to [http://localhost:3000](http://localhost:3000)

## Demo Tokens

Use these tokens to log in with different permission levels:

- **token-alice** - Member with full task permissions (read/write/delete)
- **token-bob** - Member with full task permissions
- **token-carol-viewer** - Viewer with read-only access
- **token-admin** - Admin with all permissions including user lookup

## Usage

### Task Management

1. **View Tasks**: The dashboard shows all your tasks with filtering and sorting options
2. **Create Task**: Click "Create Task" button (requires `tasks:write` scope)
3. **Edit Task**: Click "Edit" on any task card (requires `tasks:write` scope)
4. **Delete Task**: Click "Delete" on any task card (requires `tasks:delete` scope)
5. **Filter Tasks**: Use the dropdown filters for status, priority, and sorting
6. **Search Tasks**: Use the search bar to find tasks by title

### AI Agent Chat

1. Click the "AI Agent Chat" tab
2. Type natural language commands like:
   - "Create a task called 'Review PR'"
   - "List all high priority tasks"
   - "Show tasks due this week"
3. The agent will process your request and respond

**Note**: The AI chat currently uses a demo response. To enable full functionality, you need to implement an agent endpoint in the backend that connects to the TaskAgent class.

## Features by Permission

### Viewer (`tasks:read`)
- View all tasks
- Filter and search tasks
- Chat with AI agent (read-only operations)

### Member (`tasks:read`, `tasks:write`, `tasks:delete`)
- All viewer features
- Create new tasks
- Edit existing tasks
- Delete tasks

### Admin (all scopes including `users:lookup`)
- All member features
- Look up users by email
- View tasks of other users (with owner filter)

## Architecture

### Components

- **Login**: Authentication form with demo token quick-login
- **Dashboard**: Main application layout with navigation
- **TaskList**: Task list with filtering, sorting, and pagination
- **TaskForm**: Create/edit task modal form
- **AgentChat**: AI agent chat interface

### Services

- **api.ts**: API client with all backend endpoints
- **AuthContext**: Authentication state management

### Types

- Comprehensive TypeScript types for all data models
- Type-safe API calls and component props

## API Integration

The frontend integrates with these backend endpoints:

- `GET /health` - Health check
- `GET /auth/me` - Get current user
- `GET /users?email=` - Find user by email (admin only)
- `GET /tasks` - List tasks with filters
- `GET /tasks/{id}` - Get single task
- `POST /tasks` - Create task
- `PATCH /tasks/{id}` - Update task
- `DELETE /tasks/{id}` - Delete task

## Error Handling

- All API errors are displayed with user-friendly messages
- Version conflicts trigger automatic reload and retry
- Network errors show retry options
- Validation errors highlight specific fields

## Build for Production

```bash
npm run build
```

This creates an optimized production build in the `build/` directory.

## Deployment

The built files can be served by any static file server:

```bash
# Using serve
npx serve -s build

# Using Python
cd build && python -m http.server 3000
```

For production deployment, consider:
- Setting up proper CORS on the backend
- Using environment variables for API URLs
- Implementing real OAuth/JWT authentication
- Adding HTTPS
- Using a CDN for static assets

## Development

### Project Structure

```
frontend/
├── public/
│   └── index.html
├── src/
│   ├── components/
│   │   ├── Login.tsx
│   │   ├── Dashboard.tsx
│   │   ├── TaskList.tsx
│   │   ├── TaskForm.tsx
│   │   └── AgentChat.tsx
│   ├── context/
│   │   └── AuthContext.tsx
│   ├── services/
│   │   └── api.ts
│   ├── types/
│   │   └── index.ts
│   ├── App.tsx
│   ├── App.css
│   ├── index.tsx
│   └── index.css
├── package.json
├── tsconfig.json
└── README.md
```

### Adding Features

1. **New API Endpoint**: Add to `services/api.ts`
2. **New Data Type**: Add to `types/index.ts`
3. **New Component**: Create in `components/`
4. **State Management**: Use React hooks or add to AuthContext

## Troubleshooting

### Backend Connection Issues

If you see CORS errors or connection refused:

1. Make sure the backend is running on port 8000
2. Check the API URL in `.env` or `services/api.ts`
3. Verify CORS is enabled in the backend

### Authentication Issues

If authentication fails:

1. Check that you're using valid demo tokens
2. Verify the backend `/auth/me` endpoint is working
3. Clear localStorage and try again

### Task Operations Failing

If task operations fail:

1. Check your user's scopes (shown in the dashboard header)
2. Verify you have the required permissions
3. Check browser console for detailed error messages

## Contributing

When adding new features:

1. Follow TypeScript best practices
2. Add proper error handling
3. Update types as needed
4. Ensure responsive design
5. Test with different user roles

## License

Same as the main Task Agent project.
