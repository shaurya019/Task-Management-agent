import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';

const Login: React.FC = () => {
  const [token, setToken] = useState('');
  const [error, setError] = useState('');
  const { login } = useAuth();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (!token.trim()) {
      setError('Please enter a token');
      return;
    }

    try {
      await login(token);
    } catch (err) {
      setError('Invalid token. Please try again.');
    }
  };

  const quickLogin = (presetToken: string) => {
    setToken(presetToken);
  };

  return (
    <div className="login-container">
      <div className="login-box">
        <h1>Task Agent</h1>
        <p className="subtitle">AI-Powered Task Management</p>

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="token">Bearer Token</label>
            <input
              id="token"
              type="text"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="Enter your token"
              autoFocus
            />
          </div>

          {error && <div className="error-message">{error}</div>}

          <button type="submit" className="btn btn-primary">
            Login
          </button>
        </form>

        <div className="quick-login">
          <p>Quick Login (Demo Tokens):</p>
          <div className="token-buttons">
            <button onClick={() => quickLogin('token-alice')} className="btn btn-secondary">
              Alice (Member)
            </button>
            <button onClick={() => quickLogin('token-bob')} className="btn btn-secondary">
              Bob (Member)
            </button>
            <button onClick={() => quickLogin('token-carol-viewer')} className="btn btn-secondary">
              Carol (Viewer)
            </button>
            <button onClick={() => quickLogin('token-admin')} className="btn btn-secondary">
              Admin
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Login;
