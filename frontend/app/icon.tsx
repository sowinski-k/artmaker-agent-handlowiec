/* Favicon dla eCombinat - generowany dynamicznie przez Next.js w build time.
 *
 * Next.js App Router automatycznie podlinkuje ten plik jako <link rel="icon">
 * - bez potrzeby modyfikacji layout.tsx. Plik jest server-rendered raz przy
 * buildzie, potem cachowany jako PNG na poziomie HTTP.
 *
 * Design: plomien (jak w sidebar logo "ti-flame") na czarnym tle z czerwonym
 * akcentem #D4212C. Spojny z brand identity (sidebar uzywa identycznej palety).
 *
 * Apple touch icon (180x180) jest osobnym plikiem app/apple-icon.tsx.
 */
import { ImageResponse } from 'next/og';

export const size = { width: 32, height: 32 };
export const contentType = 'image/png';

export default function Icon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'linear-gradient(135deg, #1C1C1C 0%, #2A2A2A 100%)',
          borderRadius: '7px',
        }}
      >
        {/* Plomien - SVG path z Tabler icons (ti-flame), uproszczony.
            Wypelnienie czerwone #D4212C, lekki gradient dla glebi. */}
        <svg
          width="22"
          height="22"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ color: '#D4212C' }}
        >
          <path
            d="M12 12c2 -2.96 0 -7 -1 -8c0 3.038 -1.773 4.741 -3 6c-1.226 1.26 -2 3.24 -2 5a6 6 0 1 0 12 0c0 -1.532 -1.056 -3.94 -2 -5c-1.786 3 -2.791 3 -4 2z"
            fill="#D4212C"
            stroke="#D4212C"
          />
        </svg>
      </div>
    ),
    { ...size }
  );
}
