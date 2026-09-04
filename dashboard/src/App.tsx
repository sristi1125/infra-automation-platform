import { Routes, Route } from "react-router-dom";
import FleetOverview from "./FleetOverview";
import DeviceDetail from "./DeviceDetail";
import AuditLog from "./AuditLog";
import "./App.css";

function App() {
  return (
    <Routes>
      <Route path="/" element={<FleetOverview />} />
      <Route path="/devices/:id" element={<DeviceDetail />} />
      <Route path="/audit-log" element={<AuditLog />} />
    </Routes>
  );
}

export default App;