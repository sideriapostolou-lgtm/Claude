import "server-only";
import { Resend } from "resend";

let client: Resend | null = null;
function getResend(): Resend {
  if (!client) {
    const key = process.env.RESEND_API_KEY;
    if (!key) throw new Error("RESEND_API_KEY is not set");
    client = new Resend(key);
  }
  return client;
}

const FROM = process.env.RESEND_FROM_EMAIL ?? "transparency@omega-industries.com";

export async function sendEmail(opts: {
  to: string | string[];
  subject: string;
  html: string;
  text?: string;
}) {
  const resend = getResend();
  const { data, error } = await resend.emails.send({
    from: `Omega Inventory <${FROM}>`,
    to: Array.isArray(opts.to) ? opts.to : [opts.to],
    subject: opts.subject,
    html: opts.html,
    text: opts.text,
  });
  if (error) throw error;
  return data;
}

export function magicLinkEmailTemplate(params: {
  name: string;
  url: string;
  expiresInMinutes: number;
}) {
  const { name, url, expiresInMinutes } = params;
  const safeUrl = url;
  return {
    subject: "Your Omega Inventory login link",
    text:
      `Hi ${name},\n\n` +
      `Click the link below to log in to Omega Inventory. The link expires in ${expiresInMinutes} minutes.\n\n` +
      `${safeUrl}\n\n` +
      `If you did not request this, you can safely ignore this email.\n`,
    html: `
      <div style="font-family:Inter,-apple-system,Segoe UI,Roboto,sans-serif;max-width:560px;margin:0 auto;padding:24px;color:#14213d">
        <h1 style="color:#1F3864;margin:0 0 8px;font-size:20px">Omega Inventory</h1>
        <p>Hi ${escapeHtml(name)},</p>
        <p>Click the button below to log in. The link expires in ${expiresInMinutes} minutes and can only be used once.</p>
        <p style="margin:24px 0"><a href="${safeUrl}" style="background:#1F3864;color:#fff;text-decoration:none;padding:12px 20px;border-radius:8px;font-weight:600;display:inline-block">Log in</a></p>
        <p style="color:#6b7280;font-size:12px">Or paste this URL into your browser:<br><span style="word-break:break-all">${safeUrl}</span></p>
        <p style="color:#6b7280;font-size:12px;margin-top:24px">If you did not request this, you can safely ignore this email.</p>
      </div>
    `,
  };
}

function escapeHtml(s: string) {
  return s.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!)
  );
}
