import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <div className="card">
      <h2>Not found</h2>
      <div className="muted">
        This page does not exist. Go back to <Link to="/">Overview</Link>.
      </div>
    </div>
  );
}

