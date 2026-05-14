/* Apple touch icon (180x180) - dla iOS home screen + Safari.
 *
 * Next.js automatycznie podlinkuje jako <link rel="apple-touch-icon">.
 * Wieksza wersja faviconu - wieksze marginesy + lekko bigger plomien zeby
 * wygladal dobrze przy wiekszej skali na iOS home screen.
 */
import { ImageResponse } from 'next/og';

export const size = { width: 180, height: 180 };
export const contentType = 'image/png';

export default function AppleIcon() {
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
          borderRadius: '36px',
        }}
      >
        <svg
          width="120"
          height="120"
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
