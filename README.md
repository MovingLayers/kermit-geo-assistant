# Kermit GeoAssistant

An AI-powered assistant for QGIS. Type what you want to do in plain language, and GeoAI Assistant carries it out for you.

The [QGISMCP plugin](https://github.com/jjsantos01/qgis_mcp?tab=readme-ov-file#installation) by TuNombre served as the main foundation for this project.


## Contents

- [What is Kermit GeoAssistant?](#what-is-kermit-geoassistant)
- [Key Concepts](#key-concepts)
- [Developer Reference](#developer-reference)
- [Installation](#installation)
- [How to Use](#how-to-use)
  - [Moving Layers (cloud)](#moving-layers-cloud)
  - [Local LLMs](#local-llms)
- [What Can You Ask?](#what-can-you-ask)


## What is Kermit GeoAssistant?

Kermit GeoAssistant is a QGIS plugin developed by **Moving Layers GmbH** that adds a chat panel directly inside QGIS. Instead of navigating menus or writing code, you simply describe what you need in plain language — for example, *"Show me all the layers in my project"*, *"Zoom to roads layer"*, or *"Run a buffer of 500 m around the buildings"* — and an AI model carries out the action for you.

The plugin works by connecting QGIS to a Large Language Model (LLM) through the **Model Context Protocol (MCP)** — an open standard that gives the AI a controlled set of tools it can use to interact with your QGIS project. The AI reads your message, decides which tool to use, and Kermit GeoAssistant executes it inside QGIS. At no point do you need to write PyQGIS code or know the internal names of QGIS functions.

Kermit GeoAssistant is designed for a wide range of users: GIS professionals who want to speed up repetitive tasks, researchers who are new to QGIS, and anyone who finds it easier to describe a task than to look it up in documentation.

The plugin connects to an AI model in one of two ways:

| Mode | Uses | Best for |
|------|------|----------|
| Kermit | Moving Layers cloud service | Quick start, no local setup |
| Local LLMs | An LLM model running on your computer | Offline use, privacy |

**How the Moving Layers cloud connection works**

When you use the Moving Layers mode, your messages are sent over the internet to a service called *Kermit*, hosted by Moving Layers GmbH. Kermit receives your message, passes it to an AI model running on Moving Layers' servers, and streams the AI's response back to your QGIS chat panel. Think of it like sending a message to a smart assistant that lives online: you type, it thinks, it replies — and if the reply involves a QGIS action, Kermit GeoAssistant carries that action out on your computer automatically. You need a URL and an API key (a personal access code) to use this mode.

**How the Local LLMs connection works**

When you use the Local LLMs mode, everything stays on your own computer. You run a separate application called [LM Studio](https://lmstudio.ai), which downloads an AI model and runs it locally — no internet needed once the model is downloaded. Kermit GeoAssistant connects to LM Studio the same way a web browser connects to a website on your own machine: through a local address (`http://localhost:1234`). The localhost port can be set up in the LM Studio. Your messages never leave your computer, which makes this mode suitable for sensitive or confidential data. The trade-off is that you need to download and run LM Studio yourself before using this mode.

Both modes share the same chat interface — the only difference is where the AI model runs.

## Components

The plugin is built around three main parts:

- **Kermit GeoAssistant** — The chat panel inside the plugin. You type requests, connect to an AI service, and QGIS actions are carried out for you.
- **QGIS command handler** — Lives inside the plugin. It receives forwarded requests from the MCP server and carries out the actual QGIS actions — adding layers, zooming, running code, and so on.
- **MCP server** — A small background process that speaks the MCP (Model Context Protocol) standard to your AI app (LM Studio). It receives tool calls from the AI and forwards them to QGIS over a local connection.

## Developer Reference

For developers who want a quick overview of how the plugin source is organized, see [kermit_geo_assistant_plugin/plugin_structure.txt](kermit_geo_assistant_plugin/plugin_structure.txt).

## Installation

**Prerequisites**

- **QGIS 3.0 or newer** — download from [qgis.org](https://qgis.org)
- **Python** — bundled with QGIS, no separate install needed
- **uv** package manager
- Internet access and Kermit credentials (cloud mode) or [LM Studio](https://lmstudio.ai) ≥ version 0.3.17 (local mode)

**Step 1 — Download the plugin**

This creates a `kermit-geo-assistant` folder in your current directory.

1. Download the `kermit-geo-assistant` folder or if you have Git installed, open a terminal and run

```bash
git clone https://github.com/MovingLayers/kermit-geo-assistant.git
```

2. Remember its location for the step 4.4 (optional)
3. If you received a ZIP file, unzip it first. Rename the folder to `kermit-geo-assistant` from `kermit-geo-assistant-main`.
4. After downloading, confirm the inside folders:
  * `kermit_geo_assistant_plugin` contains `__init__.py`, `metadata.txt`, and `plugin.py` among others
  * `qgis_mcp_server` contains `qgis_mcp_server.py`, `pyproject.toml`

**Step 2 — Copy it to the QGIS plugins folder**

Depending on your operating system, place the plugin folder `kermit_geo_assistant_plugin` into the QGIS's plugins folder:

- macOS: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`
- Windows: `C:\Users\<YourName>\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\`
- Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`

Alternatively, you can also open the plugins folder directly from inside QGIS. Go to **Settings → User Profiles → Open Active Profile Folder**. This opens the profile folder in your file manager; navigate from there into `python/plugins/` and paste the `kermit_geo_assistant_plugin` folder there.

**Step 3 — Enable in QGIS**

1. Open QGIS. Re-openning is needed, if you placed the plugin, while QGIS was running.
2. Go to **Plugins → Manage and Install Plugins…**
3. Open the **Installed** tab.
4. Find **Kermit GeoAssistant** and tick the checkbox.
5. Click **Close**.

A **Kermit GeoAssistant** button will appear in the toolbar panel and under the Plugins menu.

**Step 4 — Set up a local model *(local mode only)***

Skip this step if you are using the Moving Layers cloud service - Kermit.

**4.1 — Install the uv package manager**

`uv` is a fast Python package manager used to run the QGIS MCP server. Install it once using the instructions for your operating system:

macOS (in Terminal):
```bash
brew install uv
```

Windows (in Command Prompt):
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Restart Windows PC for the path to uv manager to be recognized by LM Studio.

Other systems: Follow the instructions on the [uv installation page](https://docs.astral.sh/uv/getting-started/installation/).

**4.2 — Install LM Studio**

Download and install [LM Studio](https://lmstudio.ai) for your operating system. It is a free desktop application that lets you run AI models locally.

During the first openning of the application, enable the **Developer mode**.

**4.3 — Download a model**

1. Open LM Studio and click **Model search** (the search icon) in the left sidebar.
2. Search for a model. For Kermit GeoAssistant, a good balance of speed and capability is:
   - Lightweight option: `lfm2.5 1.2B` — very fast, lower hardware requirements
3. Click the model name, then click **Download** next to the variant you want. Wait for the download to complete.

**4.4 — Add the QGIS MCP tools to LM Studio**

Kermit GeoAssistant exposes a set of QGIS tools to the AI through a local TCP connection. You need to register this connection in LM Studio so the AI knows it can call QGIS functions.

1. In LM Studio, open a new chat by going to the **Chat -> New Chat** on the left-side bar. 
2. Click **Show Sidebar** button (top-right corner). There click **Integrations** -> **+ Install** -> **Edit mcp.json**.
4. Paste the following into the file (replace the path with the actual location of the qgis_mcp_server.py that was coming together with the plugin inside the `kermit-geo-assistant` folder):

   ```json
   {
     "mcpServers": {
       "qgis": {
         "command": "uv",
         "args": [
           "--directory", 
           "/ABSOLUTE/PATH/TO/kermit-geo-assistant/qgis_mcp_server",
           "run",
           "qgis_mcp_server.py"
         ]
       }
     }
   }
   ```

If the LM Studio cannot find the uv manager on Windows, replace the "command" value with the full path to the uv. Find the path by running in Command Prompt:

```powershell
where uv
```
The result should look something like this:

```json
   {
     "mcpServers": {
       "qgis": {
         "command": "C:/Users/<YourName>/.local/bin/uv.exe",
         ...
   ```

5. Save the entry. LM Studio will show `qgis` as an available tool provider under the **integrations**. Enable it.

> **What does this do?** When you ask Kermit GeoAssistant something like *"add a layer"*, the AI sends a request through this MCP connection to Kermit GeoAssistant, which then carries out the action inside QGIS. Without this step, the AI can chat but cannot control QGIS.

**4.5 — Configure and start the local server**

1. In the left sidebar, click the **Developer** icon to open the Local Server panel.
2. At the top of the panel, click the **+ Load Model** and select the model you downloaded.
3. The sidebar on the left should show model's settings. Click **Load** and set the **Context Length** to **8000** tokens. A larger context lets the AI remember more of your conversation.
4. The **mcp.json** should be set automatically
5. Click **Server Settings** and confirm that the **Server Port** is the default **1234** unless that port is already in use on your computer. In that case change it and later reference the correct port in the URL used by Kermit GeoAssistant. 
6. Enable **Require Authentication** and configure the following security options:
   - **Require Authentication** → click **Manage Token** → click **Create New Token** and copy the generated token. You will need to paste it into the **API Key** field in Kermit GeoAssistant.
   - **Allow per-request remote MCP servers** → set to **Allow**.
   - **Allow calling servers from mcp.json** → set to **Allow**.
8. Make sure **Allow per-request MCPs**, **Allow calling servers from mcp.json**, **Enable CORS** are enabled.
8. Click **Start Server**. The status indicator will turn green and you will see a message like *Server running* and *Reachable at http://127.0.0.1:1234*.

**4.6 — Keep LM Studio running**

Leave LM Studio open with the server running whenever you use Kermit GeoAssistant in Local LLMs mode. You can minimise it — it will continue serving requests in the background.


## How to Use

Click the **Kermit GeoAssistant** button in the toolbar. A panel opens on the right side of QGIS with two tabs: **Kermit** and **Local LLMs**.

**Kermit (cloud)**

Requires an API key from Moving Layers GmbH — contact [office@movinglayers.eu](mailto:office@movinglayers.eu).

1. Open the **Kermit** tab.
2. Enter the **URL** and your **API Key**.
3. Click **Connect**. The status label will show *Connected to Kermit*.
4. Type your requests in the chat box and press **Enter**.
5. Click **Disconnect** when done.

**Local LLMs**

Requires LM Studio to be running (see Step 4 above).

1. Open the **Local LLMs** tab.
2. Fill in the fields:

   | Field | What to enter | Example |
   |-------|---------------|---------|
   | **URL** | Your LLM server address | `http://localhost:1234` |
   | **API Key** | Key for your server (may be blank) | `sk-lm-…` |
   | **Model** | Model name as shown in LM Studio | `liquid/lfm2.5-1.2b` |
   | **MCP tools** | Tool string (leave as-is) | `mcp/qgis` |
   | **MCP server port** | Internal port for AI commands | `9876` |

   > **Note:** If you change the MCP server port, make sure the [qgis_mcp_server/qgis_mcp_server.py](qgis_mcp_server/qgis_mcp_server.py) references the same port.
   > ```python
   > class QgisMCPServer:
   >     def __init__(self, host='localhost', port=9876):
   >         self.host = host
   >         self.port = port
   >         self.socket = None
   > ```

3. Click **Connect**. The status label will confirm the connection.
4. Type your requests in the chat box and press **Enter**.
5. Click **Disconnect** when done.

**Chat tips**

- **Cancel** — Click **Cancel** while the AI is responding to stop it.
- **Clear history** — Use the trash icon to wipe the conversation and start fresh.
- **Follow-up messages** — Kermit GeoAssistant remembers the conversation, so you can say *"now zoom in on that layer"* without repeating yourself.


## What Can You Ask?

For example: *"List all layers in my project"*, *"Zoom to layer"*, *"Run this PyQGIS code: …"*

More capabilities will be added in future versions. For questions, contact [office@movinglayers.eu](mailto:office@movinglayers.eu) or visit [kermit.movinglayers.eu](https://kermit.movinglayers.eu).
