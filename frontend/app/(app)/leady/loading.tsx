export default function Loading() {
  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: '0 auto' }}>
      {/* Pasek filtrow */}
      <div
        style={{
          background: '#FFFFFF',
          border: '1px solid #E5E7EB',
          borderRadius: 12,
          padding: 16,
          marginBottom: 12,
          display: 'flex',
          gap: 12,
          alignItems: 'center',
        }}
      >
        <span className="skel skel-line skel-w-100" />
        <span className="skel skel-line skel-w-100" />
        <span className="skel skel-line skel-w-200" />
      </div>

      {/* Karta z tabela */}
      <div
        style={{
          background: '#FFFFFF',
          border: '1px solid #E5E7EB',
          borderRadius: 12,
          overflow: 'hidden',
        }}
      >
        <div style={{ padding: '14px 16px', borderBottom: '1px solid #E5E7EB' }}>
          <span className="skel skel-line skel-w-140" />
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: '#FAFAF7' }}>
              {['Score', 'Firma', 'Segment', 'Miasto', 'Email', 'Status', ''].map((h, i) => (
                <th
                  key={i}
                  style={{
                    padding: '10px 12px',
                    textAlign: 'left',
                    fontSize: 12,
                    color: '#6B7280',
                    textTransform: 'uppercase',
                    letterSpacing: '0.05em',
                    fontWeight: 600,
                  }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: 10 }).map((_, i) => (
              <tr key={i} style={{ borderTop: '1px solid #F3F4F6' }}>
                <td style={{ padding: '12px' }}><span className="skel skel-pill" /></td>
                <td style={{ padding: '12px' }}><span className="skel skel-line skel-w-140" /></td>
                <td style={{ padding: '12px' }}><span className="skel skel-pill" /></td>
                <td style={{ padding: '12px' }}><span className="skel skel-line skel-w-60" /></td>
                <td style={{ padding: '12px' }}><span className="skel skel-line skel-w-200" /></td>
                <td style={{ padding: '12px' }}><span className="skel skel-pill" /></td>
                <td style={{ padding: '12px' }}><span className="skel skel-line skel-w-30" /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
