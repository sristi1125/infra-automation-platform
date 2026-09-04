import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

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

function StatusBadge({ label, tone }: { label: string; tone: "good" | "bad" | "neutral" }) {
  return <span className={`badge badge-${tone}`}>{label}</span>;
}

function FleetOverview() {
  const [devices, setDevices] = useState<DeviceSummaryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

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
    return <div className="app"><p className="status-text">Loading devices...</p></div>;
  }

  if (error) {
    return <div className="app"><p className="status-text error-text">Error: {error}</p></div>;
  }

  return (
    <div className="app">
      <header className="page-header">
        <div className="header-top">
          <h1>Fleet Overview</h1>
          <button className="link-button" onClick={() => navigate("/audit-log")}>
            View Audit Log →
          </button>
        </div>
        <p className="subtitle">{devices.length} devices</p>
      </header>

      <div className="device-grid">
        {devices.map((entry) => (
          <div
            key={entry.device.id}
            className="device-card"
            onClick={() => navigate(`/devices/${entry.device.id}`)}
            style={{ cursor: "pointer" }}
          >
            <div className="card-top">
              <h2>{entry.device.name}</h2>
              <StatusBadge
                label={entry.device.health}
                tone={entry.device.health === "healthy" ? "good" : "bad"}
              />
            </div>

            <p className="card-type">{entry.device.type.toUpperCase()}</p>

            <div className="card-details">
              <div className="detail-row">
                <span className="detail-label">Power</span>
                <StatusBadge
                  label={entry.device.power}
                  tone={entry.device.power === "on" ? "good" : "neutral"}
                />
              </div>
              <div className="detail-row">
                <span className="detail-label">Firmware</span>
                <span className="detail-value">{entry.device.firmware_version}</span>
              </div>
              {entry.latest_job && (
                <div className="detail-row">
                  <span className="detail-label">Last job</span>
                  <StatusBadge
                    label={entry.latest_job.status}
                    tone={entry.latest_job.status === "succeeded" ? "good" : entry.latest_job.status === "failed" ? "bad" : "neutral"}
                  />
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default FleetOverview;