export default function Loading() {
  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: '0 auto' }}>
      <div style={{ marginBottom: 24 }}>
        <span className="skel skel-line-lg skel-block" style={{ marginBottom: 8 }} />
        <span className="skel skel-line skel-w-full" />
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            style={{
              background: '#FFFFFF',
              border: '1px solid #E5E7EB',
              borderRadius: 12,
              padding: 20,
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
              <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                <span className="skel skel-circle" />
                <span className="skel skel-line-lg skel-w-200" />
                <span className="skel skel-pill" />
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <span className="skel skel-circle" />
                <span className="skel skel-circle" />
                <span className="skel skel-circle" />
              </div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
              <span className="skel skel-line" />
              <span className="skel skel-line" />
              <span className="skel skel-line" />
              <span className="skel skel-line" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
