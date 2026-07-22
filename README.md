# ⚡ SPECTRA7

**Multi-Protocol Bombing Engine** — SMS · Voice Call · Email  
*Advanced telecommunications security assessment platform.*

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![Flask](https://img.shields.io/badge/flask-3.x-green)
![License](https://img.shields.io/badge/license-MIT-red)
![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey)

---

## 🔥 Overview

Spectra7 is an AI-integrated, multi-protocol delivery engine designed for **authorized security testing** of telecommunication systems. It combines a powerful API harvester, runtime liveness detection, intelligent concurrency control, and a real-time web dashboard into a single platform.

**42 pre-configured endpoints** harvested from 30+ community sources, plus a pattern-based generator that discovers new working APIs on the fly.

---

## 🏗️ Architecture

```
                    ┌──────────────────────────┐
                    │     Web Dashboard        │
                    │  (Flask + Socket.IO)     │
                    └──────────┬───────────────┘
                               │
                    ┌──────────▼───────────────┐
                    │      Attack Router       │
                    │    (core/bomber.py)       │
                    └──────────┬───────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
   ┌────────────┐      ┌────────────┐      ┌────────────┐
   │ SMS Engine │      │ Call Engine│      │Email Engine│
   │ 22 India   │      │  4 India   │      │  3 Multi   │
   │ 13 Multi   │      │            │      │            │
   └─────┬──────┘      └─────┬──────┘      └─────┬──────┘
         │                   │                    │
         ▼                   ▼                    ▼
   ┌─────────────────────────────────────────────────┐
   │          API Harvester + Self-Tester             │
   │  ┌──────────┐  ┌──────────┐  ┌────────────────┐ │
   │  │Community │  │ Pattern  │  │ Runtime Probe  │ │
   │  │ Scraper  │  │Generator │  │ (Liveness TTL) │ │
   │  └──────────┘  └──────────┘  └────────────────┘ │
   └─────────────────────────────────────────────────┘
```

### Concurrency Flow

```
Auto mode:  Redis (RQ) → Async (httpx) → Threaded (default)
```

Every API is recycled on each call — failures do **not** drain the pool, ensuring sustained throughput.

---

## 🚀 Quick Start

### Local (Windows / Linux / Termux)

```bash
pip install -r requirements.txt
python spectra7.py
```

First run auto-generates configuration. Dashboard at `http://127.0.0.1:5000`.

### Docker

```bash
docker build -t spectra7 .
docker run -p 5000:5000 spectra7
```

---

## 💻 CLI Usage

```bash
# Pool statistics
python cli.py info

# Test all APIs against a number (marks alive/dead)
python cli.py selftest 9876543210

# Scrape community sources for new working APIs
python cli.py harvest

# Full attack using ALL alive APIs (auto-cycling)
python cli.py massive 8489362217 200

# List alive APIs
python cli.py alive
```

### CLI Reference

| Command | Description |
|---------|-------------|
| `info` | Pool summary — counts by type, country, health |
| `selftest <number>` | Probe every endpoint, classify alive vs dead |
| `harvest [max=500]` | Scrape 30+ sources + generate pattern candidates |
| `massive <number> [count=200]` | Attack cycling through all alive APIs |
| `alive` | List every API currently marked alive |

---

## 🌐 Web Dashboard

`http://127.0.0.1:5000`

| Route | Method | Description |
|-------|--------|-------------|
| `/` | GET | Dashboard UI |
| `/api/health` | GET | Health check |
| `/api/attack` | POST | Launch attack |
| `/api/attack/<id>/status` | GET | Real-time progress |
| `/api/apis` | GET/POST | Manage API endpoints |
| `/api/apis/<type>/<index>` | DELETE | Remove endpoint |
| `/api/generate` | POST | AI message generation |
| `/api/profile` | POST | Target profiling |

---

## ☁️ Deploy on Render

1. Push to GitHub
2. Render Dashboard → New Web Service → Connect repo
3. **Build**: `pip install -r requirements.txt`
4. **Start**: `python spectra7.py`
5. **Health**: `/api/health`

### Required Environment Variables

| Variable | Description |
|----------|-------------|
| `DASHBOARD_PASSWORD` | Web UI login password |
| `FERNET_KEY` | Encryption key (auto-generated on first run) |
| `SECRET_KEY` | Flask session key (auto-generated) |
| `ENCRYPTED_NVIDIA_KEY` | Encrypted NVIDIA NIM key (optional — skip to disable AI) |

---

## 🔧 API Harvesting

Spectra7 includes a built-in harvester that scrapes 30+ community tool repositories for endpoint data, plus generates 200+ pattern-based candidates from known service patterns.

```bash
python cli.py harvest     # Discover new APIs
python cli.py selftest    # Verify which are alive
```

### Endpoint Format (`data/apis.json`)

```json
{
  "name": "redbus",
  "method": "GET",
  "url": "https://m.redbus.in/api/getOtp",
  "params": { "number": "{target}", "cc": "{cc}", "whatsAppOpted": false },
  "identifier": "200"
}
```

**Placeholders:** `{target}` = phone, `{cc}` = country code, `{message}` = AI text

**Identifier matching:** `200` (status), `2XX` (range), `@regex` (body), `!substr` (negation)

---

## ⚙️ Configuration

`.env` (auto-generated):

```env
FERNET_KEY=<auto>
ENCRYPTED_NVIDIA_KEY=<optional>
SECRET_KEY=<auto>
DASHBOARD_PASSWORD=<set this>
HOST=0.0.0.0
PORT=5000
MAX_PER_TARGET_PER_DAY=250
CONCURRENCY_MODE=auto
```

---

## 📁 Project Structure

```
spectra7/
├── spectra7.py           # Web server entry point
├── cli.py                # CLI interface
├── web/                  # Flask dashboard
│   ├── app.py            # API routes + WebSocket
│   ├── security.py       # Auth + CSRF + SSRF guard
│   └── templates/        # HTML UI
├── core/                 # Engine
│   ├── bomber.py         # Attack orchestrator
│   ├── api_aggregator.py # API management + liveness
│   ├── harvester.py      # Community scraper + probe
│   ├── email_sms.py      # Email carrier gateways
│   ├── scheduler.py      # Timing control
│   ├── keys.py           # API key management
│   └── dispatch/         # Concurrency engines
├── ai/                   # NVIDIA NIM integration
│   ├── nvidia_client.py
│   ├── message_generator.py
│   ├── sentiment.py
│   ├── translator.py
│   └── profiler.py
├── data/                 # Runtime data
│   ├── apis.json         # 42 pre-configured endpoints
│   └── categories.json   # Message templates
├── utils/                # Helpers
├── tests/
├── Dockerfile
├── render.yaml
└── requirements.txt
```

---

## 👤 Builder

**DARKSIVA**  
- Instagram: `D@RK_5!V@333`

---

## ⚠️ Legal Disclaimer

> **Spectra7 is a security research tool for authorized testing only.**  
> Unauthorized use against systems you do not own or have explicit permission to test may violate:
> - India's **IT Act 2000** & **TCCCPR 2018**
> - US **CAN-SPAM Act** & **Computer Fraud and Abuse Act**
> - EU **GDPR**
> - Similar laws worldwide
>
> The author assumes **zero liability** for misuse. You are solely responsible for legal compliance.

---

## 📜 License

MIT — Open source for legitimate security research and education.
