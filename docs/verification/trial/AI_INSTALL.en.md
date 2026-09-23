# Installation prompt to copy into your AI assistant

[简体中文](AI_INSTALL.md) | English

Use an assistant that can access local folders and run commands. Copy the entire block below. A chat-only assistant can explain the steps, but you will need to perform them yourself.

```text
Help me try A2A Contract Hub on my computer. I am not familiar with programming. Explain progress in plain English and give me one clear step at a time whenever you need me to act.

Project: https://github.com/Void107/A2A
Goal: run the included synthetic meeting demo, show internal tasks with assignees and external tasks without assignees, and explain the actual results. Run locally only. Do not deploy publicly, connect real data or work platforms, or push code.

Follow these steps:
1. Check my operating system, current directory, and existing installations. Look for this project, Docker, and Compose first. Preserve existing files and data. Do not overwrite folders, switch an existing checkout to another version, update its working tree, or reset changes. If a demo is already running or resources named a2a-alpha-local already exist, explain this and let me choose whether to reuse them. By default, obtain code from the official repository only in a new, empty folder I choose. Record the actual commit ID; for a ZIP download, record its source and download time.
2. Read AGENTS.md, README.md, and docs/verification/trial/BEGINNER.en.md. This request is only for installation and a demo, not for implementing the project's development plan. Explain any relevant Chinese instructions in English.
3. If Docker Desktop is missing, give me the official Docker installation page for my computer and guide me through installation and startup. Let me handle system passwords, license acceptance, elevated permissions, and restarts. Do not bypass permissions, disable security protections, or download installation scripts from unknown sources. Confirm that docker version can connect to the service and docker compose version works. There is no need to install Python separately on the host.
4. From the repository root containing compose.yaml, run docker compose up -d --build --wait. Explain that downloads may take time. If it fails, inspect the relevant errors; do not report success. Do not read or print .env, keys under /state, or other private files. Do not delete data volumes, run a global prune, or stop unrelated containers. Report port or network conflicts before making changes. Do not disable TLS verification or remove dependency version pins to fix downloads. Explain any complex repair before proceeding.
5. Once startup succeeds, run docker compose --profile demo run --rm demo. This creates or restores the synthetic sample's access grants; if you find an existing revocation experiment, explain the impact first. Report a successful demo only if the command exits with code 0 and actually prints: PASS: public API discovery, exact dual views, local task consumers
6. Present the actual output as an English table with task, due date, internal assignee, and external assignee (write Unassigned when empty). Do not invent results or guess the external assignee. Explain that there is no graphical product interface yet and the browser's /ready endpoint only checks readiness.
7. Ask me to read the table and explain the difference between internal and external results in one sentence. Distinguish what the AI did, what I did personally, and what remains incomplete. Do not fill in human feedback for me or claim that AC-22 human acceptance has passed.
8. Finish by telling me the project folder, version, evidence of success or failure, and how to stop with docker compose stop and resume with docker compose up -d --wait. Ask whether I want to stop now; preserve data when stopping. Do not delete data, change access permissions, or modify business code just to make the demo pass.

Do not include passwords or tokens in your output. If blocked, explain the specific reason and what I need to do next. Do not retry indefinitely or promise a fixed installation time.
```
