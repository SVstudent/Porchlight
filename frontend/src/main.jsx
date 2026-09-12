import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import './index.css';
import Dashboard from './pages/Dashboard.jsx';
import Watch from './pages/Watch.jsx';
import Neighbor from './pages/Neighbor.jsx';
import Checkin from './pages/Checkin.jsx';
import Roster from './pages/Roster.jsx';
import Demo from './pages/Demo.jsx';
import Compare from './pages/Compare.jsx';
import Report from './pages/Report.jsx';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Watch />} />
        <Route path="/neighbors/:id" element={<Neighbor />} />
        <Route path="/episodes" element={<Dashboard />} />
        <Route path="/episodes/:id" element={<Dashboard />} />
        <Route path="/episodes/:id/report" element={<Report />} />
        <Route path="/roster" element={<Roster />} />
        <Route path="/demo" element={<Demo />} />
        <Route path="/compare" element={<Compare />} />
        <Route path="/checkin/:token" element={<Checkin />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
);
