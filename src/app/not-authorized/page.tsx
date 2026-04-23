import Link from "next/link";

export default function NotAuthorized() {
  return (
    <main className="min-h-screen flex items-center justify-center bg-muted p-4">
      <div className="max-w-md bg-white rounded-xl shadow p-8 text-center">
        <h1 className="text-2xl font-semibold text-omega-navy">Not Authorized</h1>
        <p className="text-muted-foreground mt-2">
          Your account doesn&apos;t have access to this page. If you believe
          this is a mistake, please contact an admin.
        </p>
        <Link
          href="/login"
          className="inline-block mt-6 text-secondary hover:underline"
        >
          Back to login
        </Link>
      </div>
    </main>
  );
}
