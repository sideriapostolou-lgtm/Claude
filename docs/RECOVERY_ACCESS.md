# Recovery access: Railway login is complete

Status checked October 19, 2026, 1:37 PM PDT. This is an access handoff, not a
trading restart or a completed financial reconciliation.

The owner currently works from a phone. Railway CLI login and a dedicated personal
SSH public-key registration succeeded in the existing task. Do not repeat login
to address a transport failure. Private authentication stays in that workspace;
it is not in this repository and is not assumed to transfer to a new task.

The existing workspace cannot connect to `ssh.railway.com:22`. Its configured TCP
proxy also refused connection, and its TCP destination grants are empty. HTTP
platform reads work. `railway volume files` uses SFTP to the same SSH destination,
so its documented file browser is not an HTTPS alternative. No remote inspection
command has executed successfully.

## Documented web setup route

OpenAI documents editing an environment **on the web** at:

**Settings → Codex Cloud → Environments → the environment's … menu → Edit**

The owner can check whether this page is available in the phone's browser. This
menu path was verified in the official guide; availability in the owner's phone
session and support for a TCP grant have not been verified. The guide documents
HTTP/domain settings but does not document a specific TCP-access control. The
already-unrestricted HTTP setting is not a verified SSH fix.

If the existing environment is available for editing, this is the concrete setup
request to evaluate through that supported workflow:

> Configure this Codex cloud workspace for ordinary outbound SSH/SFTP to
> `ssh.railway.com` on TCP port 22 using the platform's supported TCP access and
> proxy configuration. Verify both that the grant is enforced and that the
> configured TCP connection path is reachable. If this is unsupported, report
> that limitation and the supported administrator/support action. Do not claim
> that unrestricted HTTP alone enables it. Do not change the Railway bot,
> deployments, variables, volumes, orders, money limits, loss history or stops.
> Do not create another service or tunnel around an access restriction. Preserve
> the existing task and its private files; do not copy credential values into
> messages or this repository.

The runtime plugin in this task exposes status, not a configuration writer. Its
instructions say: “Configuration changes require the environment configuration
workflow and its user review.” No such configuration change was performed.

The official guide says publishing changes affects **new tasks**, while existing
tasks retain their own state. Do not delete this task or assume its private
exports, local candidate fixes and authentication moved. Before switching, record
the exact continuation and preserve every local artifact privately; a Git checkout
alone does not contain the full operating handoff. New-task authentication must be
verified normally rather than assumed or copied into chat.

If this setup route cannot grant the destination, the next required capability is
supported TCP access from a managed environment. No phone SSH app, credential
paste, repeated sign-in or change to production is currently required from the
owner. No alternate transport was invented or used.

## What successful access must unlock

First inspect filesystem capacity/inodes and bounded file metadata read-only.
Then preserve coherent financial state/history and reconcile fresh paginated
venue records, including unresolved orders, bot-versus-owner attribution, losses
and consumed controls. The metadata helper prepared and tested under
`research/storage_recovery_2026-10-19/` does not read those financial contents and
cannot certify reconciliation or restart safety.

The last platform volume inventory reported approximately 99.958% usage; that
does not supply actual filesystem free bytes or identify deletable files.
Restart/release and profitable-entry evidence remain separate open requirements.

Sources:

- [OpenAI cloud environments: edit and republish](https://learn.chatgpt.com/docs/environments/cloud-environments#reuse-and-update-saved-state)
- [OpenAI cloud environments: connect to services](https://learn.chatgpt.com/docs/environments/cloud-environments#connect-to-services)
- [Railway SSH](https://docs.railway.com/cli/ssh)
- [Railway CLI 5.70.0 SFTP implementation](https://github.com/railwayapp/cli/blob/v5.70.0/src/commands/volume/sftp.rs)
