export default function Loading() {
  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: '0 auto' }}>
      {/* Pasek narzedzi (kampania) */}
      <div
        style={{
          background: '#FFFFFF',
          border: '1px solid #E5E7EB',
          borderRadius: 12,
          padding: 16,
          marginBottom: 16,
          display: 'flex',
          gap: 12,
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <span className="skel skel-line skel-w-140" />
        <span className="skel skel-line skel-w-200" />
      </div>

      {/* 3 karty draftow */}
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          style={{
            background: '#FFFFFF',
            border: '1px solid #E5E7EB',
            borderRadius: 12,
            padding: 18,
            marginBottom: 16,
          }}
        >
          {/* head */}
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              marginBottom: 16,
              paddingBottom: 12,
              borderBottom: '1px solid #F3F4F6',
            }}
          >
            <span className="skel skel-line-lg skel-w-200" />
            <div style={{ display: 'flex', gap: 8 }}>
              <span className="skel skel-circle" />
              <span className="skel skel-circle" />
              <span className="skel skel-circle" />
            </div>
          </div>
          {/* subject + snippets */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <span className="skel skel-line skel-w-full" />
            <span className="skel skel-line skel-w-full" />
            <span className="skel skel-line skel-w-full" />
            <span className="skel skel-line" style={{ width: '70%' }} />
            <span className="skel skel-line skel-w-full" />
            <span className="skel skel-line" style={{ width: '60%' }} />
          </div>
        </div>
      ))}
    </div>
  );
}
