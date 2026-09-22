export type TaskStatus = 'todo' | 'in_progress' | 'done';
export type Priority = 'low' | 'medium' | 'high';
export type UserRole = 'member' | 'viewer' | 'admin';

export interface Task {
  id: string;
  owner_id: string;
  title: string;
  description: string | null;
  status: TaskStatus;
  priority: Priority;
  due_date: string | null;
  tags: string[];
  version: number;
  created_at: string;
  updated_at: string;
}

export interface TaskList {
  items: Task[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface User {
  id: string;
  name: string;
  email: string;
  role: UserRole;
}

export interface MeResponse extends User {
  scopes: string[];
}

export interface TaskCreate {
  title: string;
  description?: string;
  priority?: Priority;
  due_date?: string;
  tags?: string[];
}

export interface TaskUpdate {
  title?: string;
  description?: string;
  status?: TaskStatus;
  priority?: Priority;
  due_date?: string;
  tags?: string[];
}

export interface ApiError {
  error: {
    code: string;
    message: string;
    details?: any[];
    request_id?: string;
  };
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  metadata?: {
    iterations?: number;
    tool_calls?: number;
    status?: string;
    stop_reason?: string;
  };
}

export interface TaskFilters {
  status?: TaskStatus;
  priority?: Priority;
  tag?: string;
  q?: string;
  due_before?: string;
  owner_id?: string;
  sort_by?: 'created_at' | 'updated_at' | 'due_date' | 'priority';
  order?: 'asc' | 'desc';
  limit?: number;
  offset?: number;
}
