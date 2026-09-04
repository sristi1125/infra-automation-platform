import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

const API_URL = "http://localhost:5000";
const API_KEY = "dev-viewer-key";

interface AuditEntry {
  id: number;
  actor: string;
  action: string;
  device_id: string | null;
  details: Record<string, unknown>;
  result: string;
  created_at: string;
}

function ResultBadge({ result }: { result: string }) {
  const tone = result === "success" || result === "started" ? "good" : "bad";
  return <span className={`badge badge-${tone}`}>{result}</span>;
}

function AuditLog() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    fetch(`${API_URL}/audit-log`, {
      headers: { "X-API-Key": API_KEY },
    })
      .then((res) => {
        if (!res.ok) throw new Error(`Request failed: ${res.status}`);
        return res.json();
      })
      .then((data: AuditEntry[]) => {
        setEntries(data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, []);

  if (loading) {
    return <div className="app"><p className="status-text">Loading audit log...</p></div>;
  }

  if (error) {
    return <div className="app"><p className="status-text error-text">Error: {error}</p></div>;
  }

  return (
    <div className="app">
      <button className="back-link" onClick={() => navigate("/")}>
        ← Back to Fleet
      </button>

      <header className="page-header">
        <h1>Audit Log</h1>
        <p className="subtitle">{entries.length} recorded actions</p>
      </header>

      <div className="audit-table">
        <div className="audit-row audit-header-row">
          <span>Time</span>
          <span>Actor</span>
          <span>Action</span>
          <span>Device</span>
          <span>Result</span>
        </div>
        {entries.map((entry) => (
          <div key={entry.id} className="audit-row">
            <span className="audit-time">{new Date(entry.created_at).toLocaleString()}</span>
            <span>{entry.actor}</span>
            <span>{entry.action}</span>
            <span>{entry.device_id || "—"}</span>
            <ResultBadge result={entry.result} />
          </div>
        ))}
      </div>
    </div>
  );
}

export default AuditLog;