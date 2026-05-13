export default function Loading() {
  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: '0 auto' }}>
      {/* Naglowek */}
      <div style={{ marginBottom: 24 }}>
        <span className="skel skel-line-lg skel-block skel-w-200" style={{ marginBottom: 8 }} />
        <span className="skel skel-line skel-w-full" style={{ maxWidth: 500 }} />
      </div>

      {/* Toggle trybu */}
      <div
        style={{
          background: '#FFFFFF',
          border: '1px solid #E5E7EB',
          borderRadius: 12,
          padding: 6,
          marginBottom: 16,
          display: 'inline-flex',
          gap: 4,
        }}
      >
        <span className="skel skel-line-lg skel-w-200" />
        <span className="skel skel-line-lg skel-w-200" />
      </div>

      {/* Formularz */}
      <div
        style={{
          background: '#FFFFFF',
          border: '1px solid #E5E7EB',
          borderRadius: 12,
          padding: 20,
          marginBottom: 16,
        }}
      >
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
          {[0, 1, 2, 3].map((i) => (
            <div key={i}>
              <span className="skel skel-line-sm skel-block" style={{ marginBottom: 6 }} />
              <span className="skel skel-box" style={{ height: 38 }} />
            </div>
          ))}
        </div>
        <div style={{ marginBottom: 16 }}>
          <span className="skel skel-line-sm skel-block" style={{ marginBottom: 6 }} />
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <span className="skel skel-pill skel-w-140" />
            <span className="skel skel-pill skel-w-140" />
            <span className="skel skel-pill skel-w-140" />
            <span className="skel skel-pill skel-w-140" />
          </div>
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
          <span className="skel skel-pill" style={{ height: 40, width: 180 }} />
        </div>
      </div>
    </div>
  );
}
