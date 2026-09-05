/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#0b1020',
        panel: '#141b33',
        line: '#243055',
        mut: '#8b96b8',
      },
    },
  },
  plugins: [],
}
