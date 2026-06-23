# AI Operations Center 🚀

An enterprise-grade, fully autonomous AI incident management platform. 

The AI Operations Center leverages **LangGraph**, **FastAPI**, and **Next.js** to completely automate Level 1 and Level 2 IT Support. It continuously polls incoming support emails, categorizes them by priority, diagnoses the root cause, and generates detailed post-mortem remediation plans entirely autonomously.

---

## 🌟 Key Features

*   **Autonomous Email Poller:** Automatically fetches and processes incoming tickets via IMAP.
*   **Multi-Agent Orchestration (LangGraph):**
    *   **Routing Agent:** Categorizes emails (Incident, Inquiry, Spam).
    *   **Incident Agent:** Diagnoses root causes and writes post-mortem RCAs.
    *   **Ticket Agent:** Mocks Jira/ServiceNow ticket creation.
*   **Dynamic LLM Routing:** Intelligently routes between Groq (Llama-3), Google Gemini, and local Ollama models based on task complexity and rate limits.
*   **Real-Time Analytics Dashboard:** Sleek, glassmorphism Next.js dashboard to monitor agent activity, view incident Kanban boards, and track SLAs.
*   **Knowledge Base Retrieval (RAG):** Uses Qdrant Vector Database to recall past resolutions to solve new issues faster.

---

## 🏗️ Technology Stack

| Component | Technology |
| :--- | :--- |
| **Frontend** | Next.js 14, React, Tailwind CSS, Framer Motion |
| **Backend** | Python, FastAPI, LangGraph, Uvicorn |
| **Database** | SQLite (Persistent Storage), Qdrant (Vector DB) |
| **LLM Providers**| Groq, Google Gemini API, Ollama (Local) |
| **Deployment** | Docker, Docker Compose, AWS EC2 |

---

## 🚀 Getting Started (Local Development)

### 1. Prerequisites
*   Python 3.10+
*   Node.js 18+
*   API Keys for **Groq** and **Google Gemini**

### 2. Environment Setup
Create a `.env` file in the root directory (use `.env.example` as a template) and add your keys:
```env
GROQ_API_KEY=your_groq_key
GEMINI_API_KEY=your_gemini_key
EMAIL_IMAP_HOST=imap.gmail.com
EMAIL_USERNAME=your_email@gmail.com
EMAIL_PASSWORD=your_app_password
DASHBOARD_API_KEY=your_secure_password
```

Create a `.env.local` inside the `frontend` folder:
```env
NEXT_PUBLIC_DASHBOARD_API_KEY=your_secure_password
```

### 3. Start the Platform
You can start both the frontend and backend simultaneously using the provided PowerShell script:
```powershell
.\start.ps1
```
*   **Dashboard:** `http://localhost:3000`
*   **API Docs:** `http://localhost:8000/docs`

---

## ☁️ Deployment (Docker & AWS)

This project is configured for easy deployment to an AWS EC2 instance using Docker Compose.

1. Provision an **Ubuntu** EC2 instance (t3.medium recommended).
2. Install Docker and Docker Compose on the server.
3. Clone this repository to your server.
4. Run the production build:
```bash
docker-compose -f docker-compose.prod.yml up --build -d
```
5. Your application will be live on your server's public IP at port `3000`.

---

## 🔒 Security
*   All backend API endpoints are protected by an `X-API-Key` middleware.
*   Database volumes are persistently mapped in Docker to prevent data loss across deployments.

---
