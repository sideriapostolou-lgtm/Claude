import { LoginForm } from "./login-form";

export default function LoginPage({
  searchParams,
}: {
  searchParams: { next?: string };
}) {
  return (
    <main className="min-h-screen bg-gradient-to-br from-omega-navy via-[#2a4680] to-omega-blue flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-white text-3xl font-bold tracking-tight">
            Omega Inventory
          </h1>
          <p className="text-white/80 mt-2">
            Track Panel Inventory — Vancouver, WA
          </p>
        </div>
        <div className="bg-white rounded-xl shadow-2xl p-8">
          <h2 className="text-xl font-semibold text-omega-navy mb-1">
            Log in
          </h2>
          <p className="text-sm text-muted-foreground mb-6">
            Enter your Omega email. We&apos;ll send you a one-click login link.
          </p>
          <LoginForm nextPath={searchParams.next} />
        </div>
        <p className="text-center text-white/60 text-xs mt-6">
          © {new Date().getFullYear()} Omega Industries
        </p>
      </div>
    </main>
  );
}
