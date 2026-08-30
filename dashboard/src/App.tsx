import { useEffect, useState } from "react";
import "./App.css";

const API_URL = "http://localhost:5000";
const API_KEY = "dev-viewer-key";

interface Device {
  id: string;
  name: string;
  type: string;
  power: string;
  health: string;
  firmware_version: string;
  firmware_status: string;
}

interface Job {
  id: string;
  action: string;
  status: string;
  params: Record<string, unknown>;
}

interface DeviceSummaryEntry {
  device: Device;
  latest_job: Job | null;
}

function App() {
  const [devices, setDevices] = useState<DeviceSummaryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_URL}/devices/summary`, {
      headers: { "X-API-Key": API_KEY },
    })
      .then((res) => {
        if (!res.ok) {
          throw new Error(`Request failed: ${res.status}`);
        }
        return res.json();
      })
      .then((data: DeviceSummaryEntry[]) => {
        setDevices(data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, []);

  if (loading) {
    return <div className="app">Loading devices...</div>;
  }

  if (error) {
    return <div className="app">Error: {error}</div>;
  }

  return (
    <div className="app">
      <h1>Fleet Overview</h1>
      <div className="device-grid">
        {devices.map((entry) => (
          <div key={entry.device.id} className="device-card">
            <h2>{entry.device.name}</h2>
            <p>Type: {entry.device.type}</p>
            <p>Power: {entry.device.power}</p>
            <p>Health: {entry.device.health}</p>
            <p>Firmware: {entry.device.firmware_version}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

export default App;