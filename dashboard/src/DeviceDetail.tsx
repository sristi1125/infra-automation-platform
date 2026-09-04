import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";

const API_URL = "http://localhost:5000";
const VIEWER_KEY = "dev-viewer-key";
const OPERATOR_KEY = "dev-operator-key";

interface Device {
  id: string;
  name: string;
  type: string;
  power: string;
  health: string;
  firmware_version: string;
  firmware_status: string;
}

function StatusBadge({ label, tone }: { label: string; tone: "good" | "bad" | "neutral" }) {
  return <span className={`badge badge-${tone}`}>{label}</span>;
}

function DeviceDetail() {
  const { id } = useParams();
  const navigate = useNavigate();

  const [device, setDevice] = useState<Device | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  const fetchDevice = () => {
    fetch(`${API_URL}/devices/${id}/status`, {
      headers: { "X-API-Key": VIEWER_KEY },
    })
      .then((res) => {
        if (!res.ok) throw new Error(`Request failed: ${res.status}`);
        return res.json();
      })
      .then((data: Device) => {
        setDevice(data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  };

  useEffect(() => {
    fetchDevice();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const togglePower = () => {
    if (!device) return;
    const newPower = device.power === "on" ? "off" : "on";
    setActionMessage("Working...");

    fetch(`${API_URL}/devices/${id}/power`, {
      method: "POST",
      headers: {
        "X-API-Key": OPERATOR_KEY,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ power: newPower }),
    })
      .then((res) => {
        if (!res.ok) throw new Error(`Request failed: ${res.status}`);
        return res.json();
      })
      .then((updatedDevice: Device) => {
        setDevice(updatedDevice);
        setActionMessage(`Power turned ${updatedDevice.power}`);
      })
      .catch((err) => {
        setActionMessage(`Error: ${err.message}`);
      });
  };

  const resetDevice = () => {
    setActionMessage("Resetting...");
    fetch(`${API_URL}/devices/${id}/reset`, {
      method: "POST",
      headers: { "X-API-Key": OPERATOR_KEY },
    })
      .then((res) => {
        if (!res.ok) throw new Error(`Request failed: ${res.status}`);
        return res.json();
      })
      .then(() => {
        setActionMessage("Reset complete");
        fetchDevice();
      })
      .catch((err) => {
        setActionMessage(`Error: ${err.message}`);
      });
  };

  if (loading) {
    return <div className="app"><p className="status-text">Loading...</p></div>;
  }

  if (error || !device) {
    return <div className="app"><p className="status-text error-text">Error: {error}</p></div>;
  }

  return (
    <div className="app">
      <button className="back-link" onClick={() => navigate("/")}>
        ← Back to Fleet
      </button>

      <header className="page-header">
        <h1>{device.name}</h1>
        <p className="subtitle">{device.id}</p>
      </header>

      <div className="detail-panel">
        <div className="detail-row">
          <span className="detail-label">Health</span>
          <StatusBadge label={device.health} tone={device.health === "healthy" ? "good" : "bad"} />
        </div>
        <div className="detail-row">
          <span className="detail-label">Power</span>
          <StatusBadge label={device.power} tone={device.power === "on" ? "good" : "neutral"} />
        </div>
        <div className="detail-row">
          <span className="detail-label">Firmware</span>
          <span className="detail-value">{device.firmware_version}</span>
        </div>
        <div className="detail-row">
          <span className="detail-label">Firmware status</span>
          <span className="detail-value">{device.firmware_status}</span>
        </div>
      </div>

      <div className="action-buttons">
        <button className="btn btn-primary" onClick={togglePower}>
          Turn {device.power === "on" ? "Off" : "On"}
        </button>
        <button className="btn btn-secondary" onClick={resetDevice}>
          Reset
        </button>
      </div>

      {actionMessage && <p className="action-message">{actionMessage}</p>}
    </div>
  );
}

export default DeviceDetail;