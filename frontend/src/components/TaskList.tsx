import React, { useState, useEffect } from 'react';
import { Task, TaskFilters, TaskStatus, Priority } from '../types';
import { apiClient, handleApiError } from '../services/api';
import { useAuth } from '../context/AuthContext';
import { format } from 'date-fns';

interface TaskListProps {
  onEditTask: (task: Task) => void;
  refreshTrigger?: number;
}

const TaskList: React.FC<TaskListProps> = ({ onEditTask, refreshTrigger }) => {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const { hasScope } = useAuth();

  const [filters, setFilters] = useState<TaskFilters>({
    limit: 20,
    offset: 0,
    sort_by: 'created_at',
    order: 'desc',
  });

  const [searchQuery, setSearchQuery] = useState('');

  useEffect(() => {
    fetchTasks();
  }, [filters, refreshTrigger]);

  const fetchTasks = async () => {
    setLoading(true);
    setError('');
    try {
      const result = await apiClient.listTasks(filters);
      setTasks(result.items);
      setTotal(result.total);
      setHasMore(result.has_more);
    } catch (err) {
      setError(handleApiError(err));
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!window.confirm('Are you sure you want to delete this task?')) {
      return;
    }

    try {
      await apiClient.deleteTask(id);
      fetchTasks();
    } catch (err) {
      alert(handleApiError(err));
    }
  };

  const handleSearch = () => {
    setFilters({ ...filters, q: searchQuery || undefined, offset: 0 });
  };

  const handleFilterChange = (key: keyof TaskFilters, value: any) => {
    setFilters({ ...filters, [key]: value || undefined, offset: 0 });
  };

  const nextPage = () => {
    setFilters({ ...filters, offset: (filters.offset || 0) + (filters.limit || 20) });
  };

  const prevPage = () => {
    setFilters({ ...filters, offset: Math.max(0, (filters.offset || 0) - (filters.limit || 20)) });
  };

  const getPriorityColor = (priority: Priority) => {
    switch (priority) {
      case 'high': return '#e74c3c';
      case 'medium': return '#f39c12';
      case 'low': return '#3498db';
    }
  };

  const getStatusColor = (status: TaskStatus) => {
    switch (status) {
      case 'todo': return '#95a5a6';
      case 'in_progress': return '#3498db';
      case 'done': return '#2ecc71';
    }
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return '-';
    try {
      return format(new Date(dateStr), 'MMM d, yyyy');
    } catch {
      return dateStr;
    }
  };

  const isOverdue = (dueDate: string | null, status: TaskStatus) => {
    if (!dueDate || status === 'done') return false;
    return new Date(dueDate) < new Date();
  };

  return (
    <div className="task-list-container">
      <div className="filters-panel">
        <div className="search-bar">
          <input
            type="text"
            placeholder="Search tasks..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyPress={(e) => e.key === 'Enter' && handleSearch()}
          />
          <button onClick={handleSearch} className="btn btn-primary">Search</button>
        </div>

        <div className="filters-row">
          <select
            value={filters.status || ''}
            onChange={(e) => handleFilterChange('status', e.target.value)}
          >
            <option value="">All Status</option>
            <option value="todo">To Do</option>
            <option value="in_progress">In Progress</option>
            <option value="done">Done</option>
          </select>

          <select
            value={filters.priority || ''}
            onChange={(e) => handleFilterChange('priority', e.target.value)}
          >
            <option value="">All Priority</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
          </select>

          <select
            value={filters.sort_by || 'created_at'}
            onChange={(e) => handleFilterChange('sort_by', e.target.value)}
          >
            <option value="created_at">Created Date</option>
            <option value="updated_at">Updated Date</option>
            <option value="due_date">Due Date</option>
            <option value="priority">Priority</option>
          </select>

          <select
            value={filters.order || 'desc'}
            onChange={(e) => handleFilterChange('order', e.target.value)}
          >
            <option value="desc">Descending</option>
            <option value="asc">Ascending</option>
          </select>
        </div>
      </div>

      {error && <div className="error-message">{error}</div>}

      <div className="task-count">
        Showing {tasks.length} of {total} tasks
      </div>

      {loading ? (
        <div className="loading">Loading tasks...</div>
      ) : (
        <>
          <div className="tasks-grid">
            {tasks.map((task) => (
              <div key={task.id} className="task-card">
                <div className="task-header">
                  <h3>{task.title}</h3>
                  <div className="task-badges">
                    <span
                      className="badge status-badge"
                      style={{ backgroundColor: getStatusColor(task.status) }}
                    >
                      {task.status.replace('_', ' ')}
                    </span>
                    <span
                      className="badge priority-badge"
                      style={{ backgroundColor: getPriorityColor(task.priority) }}
                    >
                      {task.priority}
                    </span>
                  </div>
                </div>

                {task.description && (
                  <p className="task-description">{task.description}</p>
                )}

                <div className="task-meta">
                  <div className="meta-item">
                    <strong>Due:</strong>
                    <span className={isOverdue(task.due_date, task.status) ? 'overdue' : ''}>
                      {formatDate(task.due_date)}
                    </span>
                  </div>
                  <div className="meta-item">
                    <strong>Created:</strong> {formatDate(task.created_at)}
                  </div>
                </div>

                {task.tags.length > 0 && (
                  <div className="task-tags">
                    {task.tags.map((tag) => (
                      <span key={tag} className="tag">
                        {tag}
                      </span>
                    ))}
                  </div>
                )}

                <div className="task-footer">
                  <span className="task-id">{task.id}</span>
                  <div className="task-actions">
                    {hasScope('tasks:write') && (
                      <button
                        onClick={() => onEditTask(task)}
                        className="btn btn-small btn-secondary"
                      >
                        Edit
                      </button>
                    )}
                    {hasScope('tasks:delete') && (
                      <button
                        onClick={() => handleDelete(task.id)}
                        className="btn btn-small btn-danger"
                      >
                        Delete
                      </button>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>

          {tasks.length === 0 && !loading && (
            <div className="empty-state">
              <p>No tasks found. Create your first task or try adjusting filters.</p>
            </div>
          )}

          <div className="pagination">
            <button
              onClick={prevPage}
              disabled={!filters.offset}
              className="btn btn-secondary"
            >
              Previous
            </button>
            <span className="pagination-info">
              Page {Math.floor((filters.offset || 0) / (filters.limit || 20)) + 1}
            </span>
            <button
              onClick={nextPage}
              disabled={!hasMore}
              className="btn btn-secondary"
            >
              Next
            </button>
          </div>
        </>
      )}
    </div>
  );
};

export default TaskList;
