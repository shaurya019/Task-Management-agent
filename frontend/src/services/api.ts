import axios, { AxiosError } from 'axios';
import { Task, TaskList, TaskCreate, TaskUpdate, User, MeResponse, TaskFilters, ApiError } from '../types';

const API_BASE_URL = process.env.REACT_APP_API_BASE_URL || 'http://127.0.0.1:8000';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor to add auth token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('auth_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Response interceptor to handle errors
api.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiError>) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('auth_token');
      window.location.href = '/';
    }
    return Promise.reject(error);
  }
);

export const apiClient = {
  // Health check
  async healthCheck(): Promise<{ status: string }> {
    const { data } = await api.get('/health');
    return data;
  },

  // Auth
  async getMe(): Promise<MeResponse> {
    const { data } = await api.get('/auth/me');
    return data;
  },

  // Users
  async findUser(email: string): Promise<User> {
    const { data } = await api.get(`/users?email=${encodeURIComponent(email)}`);
    return data;
  },

  // Tasks - List
  async listTasks(filters?: TaskFilters): Promise<TaskList> {
    const params = new URLSearchParams();
    if (filters) {
      Object.entries(filters).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') {
          params.append(key, String(value));
        }
      });
    }
    const { data } = await api.get(`/tasks?${params.toString()}`);
    return data;
  },

  // Tasks - Get single
  async getTask(id: string): Promise<{ task: Task; version: string }> {
    const response = await api.get(`/tasks/${id}`);
    const version = response.headers['etag']?.replace(/"/g, '') || String(response.data.version);
    return { task: response.data, version };
  },

  // Tasks - Create
  async createTask(task: TaskCreate): Promise<Task> {
    const idempotencyKey = `create-${Date.now()}-${Math.random()}`;
    const { data } = await api.post('/tasks', task, {
      headers: {
        'Idempotency-Key': idempotencyKey,
      },
    });
    return data;
  },

  // Tasks - Update (PATCH)
  async updateTask(id: string, updates: TaskUpdate, expectedVersion?: string): Promise<Task> {
    const headers: Record<string, string> = {};
    if (expectedVersion) {
      headers['If-Match'] = `"${expectedVersion}"`;
    }
    const { data } = await api.patch(`/tasks/${id}`, updates, { headers });
    return data;
  },

  // Tasks - Delete
  async deleteTask(id: string): Promise<void> {
    await api.delete(`/tasks/${id}`);
  },

  // Agent chat
  async sendAgentMessage(message: string): Promise<any> {
    const { data } = await api.post('/agent/chat', { message });
    return data;
  },
};

export const handleApiError = (error: unknown): string => {
  if (axios.isAxiosError(error)) {
    const apiError = error.response?.data as ApiError;
    if (apiError?.error) {
      return apiError.error.message;
    }
    return error.message;
  }
  return 'An unexpected error occurred';
};
