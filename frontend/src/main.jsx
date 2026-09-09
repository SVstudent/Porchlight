import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import './index.css';
import Dashboard from './pages/Dashboard.jsx';
import Checkin from './pages/Checkin.jsx';
import Roster from './pages/Roster.jsx';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/episodes/:id" element={<Dashboard />} />
        <Route path="/roster" element={<Roster />} />
        <Route path="/checkin/:token" element={<Checkin />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
);
