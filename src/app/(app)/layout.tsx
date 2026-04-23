import { redirect } from "next/navigation";
import Link from "next/link";
import { getCurrentUser } from "@/lib/session";
import {
  LayoutDashboard,
  Package,
  Wrench,
  FileBarChart,
  Settings,
  LogOut,
  PlusCircle,
} from "lucide-react";

export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const user = await getCurrentUser();
  if (!user) redirect("/login");

  const isAdmin = user.role === "admin";

  return (
    <div className="min-h-screen bg-background flex flex-col md:flex-row">
      <aside className="md:w-56 md:min-h-screen bg-omega-navy text-white md:sticky md:top-0 md:self-start flex-shrink-0">
        <div className="px-5 py-5 border-b border-white/10">
          <div className="text-lg font-semibold tracking-tight">Omega</div>
          <div className="text-xs text-white/60 -mt-0.5">Inventory · Vancouver</div>
        </div>
        <nav className="p-3 space-y-0.5 text-sm">
          <NavLink href="/" icon={<LayoutDashboard size={16} />}>
            Dashboard
          </NavLink>
          <NavLink href="/raw-materials" icon={<Wrench size={16} />}>
            Raw materials
          </NavLink>
          <NavLink href="/finished-goods" icon={<Package size={16} />}>
            Finished goods
          </NavLink>
          <NavLink href="/reports/weekly" icon={<FileBarChart size={16} />}>
            Weekly report
          </NavLink>

          {isAdmin && (
            <>
              <div className="pt-4 pb-1 px-3 text-[10px] uppercase tracking-wider text-white/50">
                Log activity
              </div>
              <NavLink href="/log/build" icon={<PlusCircle size={16} />}>
                Build
              </NavLink>
              <NavLink href="/log/shipment" icon={<PlusCircle size={16} />}>
                Shipment
              </NavLink>
              <NavLink href="/log/receipt" icon={<PlusCircle size={16} />}>
                Receipt
              </NavLink>

              <div className="pt-4 pb-1 px-3 text-[10px] uppercase tracking-wider text-white/50">
                Admin
              </div>
              <NavLink href="/admin/users" icon={<Settings size={16} />}>
                Users
              </NavLink>
              <NavLink href="/admin/panels" icon={<Settings size={16} />}>
                Panel types
              </NavLink>
              <NavLink href="/admin/bulk-count" icon={<Settings size={16} />}>
                Bulk count
              </NavLink>
            </>
          )}
        </nav>

        <div className="mt-auto p-3 border-t border-white/10 text-xs md:fixed md:bottom-0 md:w-56 bg-omega-navy">
          <div className="px-2 py-1 truncate" title={user.email}>
            {user.name}
          </div>
          <div className="px-2 text-white/60 capitalize">{user.role}</div>
          <form action="/api/auth/logout" method="post" className="mt-2 px-2">
            <button
              type="submit"
              className="inline-flex items-center gap-1.5 text-white/70 hover:text-white"
            >
              <LogOut size={14} /> Log out
            </button>
          </form>
        </div>
      </aside>
      <main className="flex-1 min-w-0 p-4 md:p-8 pb-24">{children}</main>
    </div>
  );
}

function NavLink({
  href,
  icon,
  children,
}: {
  href: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className="flex items-center gap-2 px-3 py-2 rounded-md hover:bg-white/10 transition-colors"
    >
      <span className="text-white/70">{icon}</span>
      <span>{children}</span>
    </Link>
  );
}
