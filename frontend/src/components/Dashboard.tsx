import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import TaskList from './TaskList';
import TaskForm from './TaskForm';
import AgentChat from './AgentChat';
import { Task } from '../types';

const Dashboard: React.FC = () => {
  const { user, logout, hasScope } = useAuth();
  const [activeTab, setActiveTab] = useState<'tasks' | 'chat'>('tasks');
  const [showTaskForm, setShowTaskForm] = useState(false);
  const [editingTask, setEditingTask] = useState<Task | undefined>(undefined);
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  const handleCreateTask = () => {
    setEditingTask(undefined);
    setShowTaskForm(true);
  };

  const handleEditTask = (task: Task) => {
    setEditingTask(task);
    setShowTaskForm(true);
  };

  const handleFormSuccess = () => {
    setRefreshTrigger((prev) => prev + 1);
  };

  const handleCloseForm = () => {
    setShowTaskForm(false);
    setEditingTask(undefined);
  };

  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <div className="header-left">
          <h1>Task Agent</h1>
        </div>
        <div className="header-right">
          <div className="user-info">
            <div>
              <strong>{user?.name}</strong>
              <span className="user-role">{user?.role}</span>
            </div>
            <div className="user-email">{user?.email}</div>
          </div>
          <button onClick={logout} className="btn btn-secondary">
            Logout
          </button>
        </div>
      </header>

      <div className="user-scopes">
        <strong>Permissions:</strong>
        {user?.scopes.map((scope) => (
          <span key={scope} className="scope-badge">
            {scope}
          </span>
        ))}
      </div>

      <nav className="dashboard-nav">
        <button
          className={`nav-btn ${activeTab === 'tasks' ? 'active' : ''}`}
          onClick={() => setActiveTab('tasks')}
        >
          Task Management
        </button>
        <button
          className={`nav-btn ${activeTab === 'chat' ? 'active' : ''}`}
          onClick={() => setActiveTab('chat')}
        >
          AI Agent Chat
        </button>
      </nav>

      <main className="dashboard-content">
        {activeTab === 'tasks' && (
          <div className="tasks-view">
            <div className="tasks-header">
              <h2>Your Tasks</h2>
              {hasScope('tasks:write') && (
                <button onClick={handleCreateTask} className="btn btn-primary">
                  + Create Task
                </button>
              )}
            </div>
            <TaskList onEditTask={handleEditTask} refreshTrigger={refreshTrigger} />
          </div>
        )}

        {activeTab === 'chat' && <AgentChat />}
      </main>

      {showTaskForm && (
        <TaskForm
          task={editingTask}
          onClose={handleCloseForm}
          onSuccess={handleFormSuccess}
        />
      )}
    </div>
  );
};

export default Dashboard;
