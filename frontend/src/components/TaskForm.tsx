import React, { useState, useEffect } from 'react';
import { Task, TaskCreate, TaskUpdate, TaskStatus, Priority } from '../types';
import { apiClient, handleApiError } from '../services/api';

interface TaskFormProps {
  task?: Task;
  onClose: () => void;
  onSuccess: () => void;
}

const TaskForm: React.FC<TaskFormProps> = ({ task, onClose, onSuccess }) => {
  const [formData, setFormData] = useState<TaskCreate | TaskUpdate>({
    title: task?.title || '',
    description: task?.description || '',
    status: task?.status || 'todo',
    priority: task?.priority || 'medium',
    due_date: task?.due_date || '',
    tags: task?.tags || [],
  });

  const [tagsInput, setTagsInput] = useState(task?.tags.join(', ') || '');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [version, setVersion] = useState<string>('');

  useEffect(() => {
    if (task) {
      fetchTaskVersion();
    }
  }, [task]);

  const fetchTaskVersion = async () => {
    if (!task) return;
    try {
      const { version: v } = await apiClient.getTask(task.id);
      setVersion(v);
    } catch (err) {
      console.error('Failed to fetch task version:', err);
    }
  };

  const handleChange = (field: string, value: any) => {
    setFormData({ ...formData, [field]: value });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');

    try {
      const tags = tagsInput
        .split(',')
        .map((t) => t.trim().toLowerCase())
        .filter((t) => t.length > 0);

      const submitData = {
        ...formData,
        tags,
        description: formData.description || undefined,
        due_date: formData.due_date || undefined,
      };

      if (task) {
        // Update existing task
        await apiClient.updateTask(task.id, submitData as TaskUpdate, version);
      } else {
        // Create new task
        await apiClient.createTask(submitData as TaskCreate);
      }

      onSuccess();
      onClose();
    } catch (err: any) {
      const errorMsg = handleApiError(err);

      // Handle version conflict
      if (err.response?.data?.error?.code === 'version_conflict') {
        setError('Task was modified by someone else. Reloading...');
        setTimeout(() => {
          fetchTaskVersion();
          setError('Task reloaded. Please review and resubmit.');
        }, 1000);
      } else {
        setError(errorMsg);
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>{task ? 'Edit Task' : 'Create Task'}</h2>
          <button onClick={onClose} className="close-btn">&times;</button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="title">Title *</label>
            <input
              id="title"
              type="text"
              value={formData.title}
              onChange={(e) => handleChange('title', e.target.value)}
              required
              maxLength={120}
              placeholder="Enter task title"
            />
          </div>

          <div className="form-group">
            <label htmlFor="description">Description</label>
            <textarea
              id="description"
              value={formData.description || ''}
              onChange={(e) => handleChange('description', e.target.value)}
              maxLength={2000}
              rows={4}
              placeholder="Enter task description (optional)"
            />
          </div>

          <div className="form-row">
            {task && (
              <div className="form-group">
                <label htmlFor="status">Status</label>
                <select
                  id="status"
                  value={formData.status}
                  onChange={(e) => handleChange('status', e.target.value as TaskStatus)}
                >
                  <option value="todo">To Do</option>
                  <option value="in_progress">In Progress</option>
                  <option value="done">Done</option>
                </select>
              </div>
            )}

            <div className="form-group">
              <label htmlFor="priority">Priority</label>
              <select
                id="priority"
                value={formData.priority}
                onChange={(e) => handleChange('priority', e.target.value as Priority)}
              >
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
            </div>

            <div className="form-group">
              <label htmlFor="due_date">Due Date</label>
              <input
                id="due_date"
                type="date"
                value={formData.due_date || ''}
                onChange={(e) => handleChange('due_date', e.target.value)}
              />
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="tags">Tags (comma-separated)</label>
            <input
              id="tags"
              type="text"
              value={tagsInput}
              onChange={(e) => setTagsInput(e.target.value)}
              placeholder="e.g., urgent, backend, review"
            />
            <small>Max 10 tags, will be converted to lowercase</small>
          </div>

          {error && <div className="error-message">{error}</div>}

          <div className="modal-footer">
            <button type="button" onClick={onClose} className="btn btn-secondary">
              Cancel
            </button>
            <button type="submit" disabled={loading} className="btn btn-primary">
              {loading ? 'Saving...' : task ? 'Update Task' : 'Create Task'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default TaskForm;
