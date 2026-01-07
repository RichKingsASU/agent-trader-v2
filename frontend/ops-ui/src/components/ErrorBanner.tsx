export function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="error">
      <div style={{ fontWeight: 600, marginBottom: 4 }}>Cannot reach API</div>
      <div className="mono">{message}</div>
    </div>
  );
}

