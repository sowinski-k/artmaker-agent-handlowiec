export default function Loading() {
  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: '0 auto' }}>
      {/* Naglowek workspace */}
      <div style={{ marginBottom: 24 }}>
        <span className="skel skel-line-lg skel-block skel-w-200" style={{ marginBottom: 8 }} />
        <span className="skel skel-line skel-w-100" />
      </div>

      {/* 4 karty KPI */}
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
            <span className="skel skel-line-sm skel-block" style={{ marginBottom: 12 }} />
            <span className="skel skel-line-lg skel-block skel-w-100" style={{ marginBottom: 8 }} />
            <span className="skel skel-line skel-w-60" />
          </div>
        ))}
      </div>

      {/* 2 kolumny: aktywne joby + moduly */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 16 }}>
        <div
          style={{
            background: '#FFFFFF',
            border: '1px solid #E5E7EB',
            borderRadius: 12,
            padding: 16,
          }}
        >
          <span className="skel skel-line skel-w-140 skel-block" style={{ marginBottom: 16 }} />
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              style={{
                padding: 12,
                background: '#FAFAF7',
                borderRadius: 8,
                marginBottom: 8,
                display: 'flex',
                justifyContent: 'space-between',
              }}
            >
              <span className="skel skel-line skel-w-200" />
              <span className="skel skel-pill" />
            </div>
          ))}
        </div>
        <div
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
                gap: 12,
                alignItems: 'center',
                padding: '10px 0',
              }}
            >
              <span className="skel skel-circle" />
              <div style={{ flex: 1 }}>
                <span className="skel skel-line skel-w-140 skel-block" style={{ marginBottom: 4 }} />
                <span className="skel skel-line-sm skel-w-60" />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
