import type { Metadata } from 'next';
import Link from 'next/link';
import './globals.css';
import ThemeProvider from '@/components/ThemeProvider';
import ThemeToggle from '@/components/ThemeToggle';
import ThemePicker from '@/components/ThemePicker';
import JobStatusProvider from '@/components/JobStatusProvider';
import AuthProvider from '@/components/AuthProvider';
import NavAuthButton from '@/components/NavAuthButton';
import pkg from '@/package.json';

export const metadata: Metadata = {
  title: 'Vidistiller',
  description: 'Turn any video into structured documentation',
};

const themeInitScript = `
(function() {
  try {
    var mode = localStorage.getItem('theme') || 'dark';
    var themeId = localStorage.getItem('vidistiller-theme') || 'lunaris';
    if (mode === 'dark') document.documentElement.classList.add('dark');
    document.documentElement.setAttribute('data-theme', themeId);
  } catch(e) {}
})();
`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&display=swap" rel="stylesheet" />
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className="flex flex-col h-screen overflow-hidden">
        <ThemeProvider>
          <AuthProvider>
          <JobStatusProvider>
            <nav className="bg-card-light dark:bg-card-dark shadow dark:shadow-gray-900 shrink-0">
              <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                <div className="flex justify-between h-20">
                  <div className="flex items-center">
                    <div className="flex flex-col">
                      <h1 className="text-2xl font-bold text-text-dark dark:text-text-light leading-tight">
                        vidistiller
                      </h1>
                      <span className="text-xs font-mono text-text-dark/30 dark:text-text-light/30 leading-none">
                        v{pkg.version}
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center space-x-4">
                    <Link href="/" className="text-text-dark/70 hover:text-text-dark dark:text-text-light/70 dark:hover:text-text-light">
                      home
                    </Link>
                    <ThemePicker />
                    <ThemeToggle />
                  </div>
                  <div className="flex items-center">
                    <NavAuthButton />
                  </div>
                </div>
              </div>
            </nav>
            <main className="flex-1 overflow-auto">
              {children}
            </main>
          </JobStatusProvider>
          </AuthProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
