# Your first demo: one meeting, two task lists

[简体中文](BEGINNER.md) | English

You do not need to know how to code. This demo uses a fictional meeting included with the project to show how internal colleagues and external partners receive different information. It does not send messages or create tasks in a real work platform.

This is a local demo, with no graphical product interface yet. Results appear in a terminal: the window where you enter commands and read their output. An AI assistant can help you install the demo and explain the results.

## Option A: ask an AI assistant to help (recommended)

1. Use an AI assistant that can read local files and run terminal commands. Open a new, empty folder. A chat-only assistant can guide you, but cannot install the project for you.
2. Open the [AI installation prompt](AI_INSTALL.en.md) and copy the entire prompt into your assistant.
3. Follow its instructions to install and open Docker Desktop, which runs the supporting services needed by this demo. Handle system permissions, software license acceptance, and any required restart yourself. Do not share your computer password with the AI.
4. Wait for the assistant to report the result. Ask it to present the two task lists in a simple English table. Internal tasks should have assignees; external tasks should be unassigned.
5. When finished, tell the assistant: “Stop this demo and keep its data.” You can resume later.

What the assistant can do depends on its permissions. Network access, device requirements, and system permissions may still require your help. If setup gets stuck, keep the error message instead of repeatedly reinstalling.

## Option B: follow the steps yourself

### 1. Install and open Docker Desktop

Follow the official instructions for your computer: [Mac](https://docs.docker.com/desktop/setup/install/mac-install/), [Windows](https://docs.docker.com/desktop/setup/install/windows-install/), or [Linux](https://docs.docker.com/desktop/setup/install/linux/). Open Docker Desktop after installation and wait for it to start. On Windows, use Linux containers. If the installer asks you to set up WSL or restart, follow the official instructions.

The project has verification evidence from a local Mac and hosted Ubuntu checks. Installation by a nontechnical Windows user has not yet been verified. You do not need to install Python separately, buy AI API access, or supply an API key for this demo.

### 2. Download the project

Open the [project repository](https://github.com/Void107/A2A), select **Code → Download ZIP**, and extract it into a new folder. Do not overwrite an existing project.

Open the extracted folder containing `compose.yaml` and `README.md`, then open a terminal in that folder. On Windows, you can right-click an empty area of the folder and choose **Open in Terminal**. On Mac, open Terminal, type `cd ` (including the trailing space), drag the folder into the terminal window, and press Enter.

### 3. Start the demo environment

Copy this line into the terminal and press Enter:

```sh
docker compose up -d --build --wait
```

The first run downloads dependencies. How long it takes depends on your computer and network; a lot of download output is normal. Wait for the command to finish without errors before continuing. If it fails, stop and investigate rather than assuming setup succeeded.

### 4. View the two task lists

```sh
docker compose --profile demo run --rm demo
```

A successful run ends with this exact line:

```text
PASS: public API discovery, exact dual views, local task consumers
```

The two groups above it mean:

| Name in the output | Who it is for | What you should see |
| --- | --- | --- |
| internal-project | Internal colleagues | Two tasks with due dates and assignee email addresses; assignment_state is assigned |
| external-collaboration | External partners | Two tasks with due dates and no assignee; assignment_state is unassigned |

Processing covers predefined fields and ordinary English email addresses. It does not guarantee removal of names, phone numbers, or obfuscated email addresses from arbitrary text. Use the included sample; do not import real meeting or customer information.

If the PASS line is missing, the demo has not passed. Opening `http://127.0.0.1:58000/ready` in a browser can help check readiness, but a status response does not mean the demo completed. The root address does not show a product homepage.

### 5. Stop now and resume later

Run this in the same project folder:

```sh
docker compose stop
```

This stops the services and keeps their data. Next time, open Docker Desktop first, then run:

```sh
docker compose up -d --wait
docker compose --profile demo run --rm demo
```

The demo reestablishes the sample access grants. Do not use it to check whether access revoked in an earlier experiment remains revoked. Do not run commands that delete data volumes or clear all Docker resources.

## If you get stuck

| What you see | What to try first |
| --- | --- |
| docker command not found | Check that Docker Desktop is installed, then reopen the terminal |
| Cannot connect to Docker | Open Docker Desktop and wait for startup to finish |
| Configuration file not found | Return to the folder containing compose.yaml |
| Download interrupted or timed out | Check your connection and retry the startup command. Keep certificate verification enabled. If failures persist, share the error with your AI assistant or the maintainer |
| Port or network conflict | Stop and ask the assistant to investigate. Do not stop unfamiliar services or change settings at random |
| A service fails or PASS is missing | Keep the final error message and ask for an explanation. Do not erase data and reinstall |

When asking for help, provide your operating system, the step that failed, and the error with sensitive information removed. Do not share `.env` files, keys, tokens, passwords, or full computer logs.

## Tell us three things

1. Did you see PASS? Which step was hardest?
2. In your own words, how do the internal and external tasks differ?
3. Did an AI assistant or another person help? What did they do?

Beginner feedback and developer integration acceptance are recorded separately. An AI assistant successfully running the demo does not mean you independently completed developer acceptance or that the product is ready for production.
