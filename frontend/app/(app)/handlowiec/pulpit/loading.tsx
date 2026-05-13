export default function Loading() {
  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: '0 auto' }}>
      {/* Topbar */}
      <div style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between' }}>
        <span className="skel skel-line skel-w-140" />
        <span className="skel skel-pill" />
      </div>

      {/* 4 KPI ze sparklines */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: 16,
          marginBottom: 24,
        }}
      >
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            style={{
              background: '#FFFFFF',
              border: '1px solid #E5E7EB',
              borderRadius: 12,
              padding: 18,
            }}
          >
            <span className="skel skel-line-sm skel-block" style={{ marginBottom: 8 }} />
            <span
              className="skel skel-line-lg skel-block skel-w-100"
              style={{ marginBottom: 12 }}
            />
            <span className="skel skel-box" style={{ height: 24 }} />
          </div>
        ))}
      </div>

      {/* Funnel */}
      <div
        style={{
          background: '#FFFFFF',
          border: '1px solid #E5E7EB',
          borderRadius: 12,
          padding: 18,
          marginBottom: 16,
        }}
      >
        <span className="skel skel-line skel-w-100 skel-block" style={{ marginBottom: 16 }} />
        {[0, 1, 2, 3, 4].map((i) => (
          <div
            key={i}
            style={{
              display: 'flex',
              gap: 12,
              alignItems: 'center',
              marginBottom: 10,
            }}
          >
            <span className="skel skel-line skel-w-100" />
            <span className="skel skel-box" style={{ height: 12, flex: 1 }} />
            <span className="skel skel-line skel-w-30" />
          </div>
        ))}
      </div>

      {/* 2 kolumny: segmenty + system */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {[0, 1].map((c) => (
          <div
            key={c}
            style={{
              background: '#FFFFFF',
              border: '1px solid #E5E7EB',
              borderRadius: 12,
              padding: 16,
            }}
          >
            <span className="skel skel-line skel-w-100 skel-block" style={{ marginBottom: 16 }} />
            {[0, 1, 2, 3].map((i) => (
              <div
                key={i}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  padding: '8px 0',
                  borderBottom: '1px solid #F3F4F6',
                }}
              >
                <span className="skel skel-line skel-w-140" />
                <span className="skel skel-pill" />
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
